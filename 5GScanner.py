#!/usr/bin/env python3
"""
fiveg_room_scanner.py

Conceptual "best possible" 5G NIC-based room scanner pipeline.

What this script does:
- Defines a CSI data model (per-subcarrier, per-antenna complex channel estimates).
- Streams CSI frames (by default from a simulator; hook real hardware where marked).
- Converts CSI to CIR (delay / range profile) via IFFT across subcarriers.
- Maintains a background model to remove static clutter.
- Computes a simple presence score.
- Displays a live "range vs time" waterfall of residual energy using matplotlib.

To run (simulation):
    python fiveg_room_scanner.py

To integrate real hardware:
    - Replace `SimulatedFiveGCSIStream` with a class that reads your 5G NIC / SDR
      and yields CSIFrame instances.

Dependencies:
    pip install numpy matplotlib
"""

import argparse
import time
import threading
from collections import deque
from dataclasses import dataclass
from typing import Generator, Optional

import numpy as np
import matplotlib.pyplot as plt


# ==========================
# Data structures
# ==========================

@dataclass
class CSIFrame:
    """
    Container for a single CSI frame (one time step).
    """
    timestamp: float
    carrier_freq: float          # Hz
    subcarrier_spacing: float    # Hz
    bandwidth: float             # Hz
    nrx: int                     # number of RX antennas
    ntx: int                     # number of TX antennas
    csi: np.ndarray              # complex CSI, shape [n_sym, n_sc, nrx, ntx]


# ==========================
# Acquisition layer
# ==========================

class SimulatedFiveGCSIStream:
    """
    Simulator for a 5G CSI stream.

    - Generates OFDM CSI with:
        - A static background (room reflections)
        - One moving target whose delay (range tap) changes over time

    This is just to let you see the processing + visualization pipeline working.
    """

    def __init__(self,
                 n_sc: int = 256,
                 nrx: int = 4,
                 ntx: int = 1,
                 subcarrier_spacing: float = 60e3,  # 60 kHz typical for 5G
                 carrier_freq: float = 3.5e9,       # 3.5 GHz FR1 example
                 frame_rate: float = 20.0):
        self.n_sc = n_sc
        self.nrx = nrx
        self.ntx = ntx
        self.subcarrier_spacing = subcarrier_spacing
        self.carrier_freq = carrier_freq
        self.bandwidth = n_sc * subcarrier_spacing
        self.frame_interval = 1.0 / frame_rate
        self._running = True
        self._t0 = time.time()

        # Pre-compute subcarrier frequencies (baseband)
        k = np.arange(-n_sc // 2, n_sc // 2)
        self.freqs = k * self.subcarrier_spacing

        # Static background CIR (random multipath)
        rng = np.random.default_rng(42)
        n_taps_bg = 16
        taps_bg = np.zeros(self.n_sc, dtype=np.complex64)
        tap_indices_bg = rng.integers(low=0, high=self.n_sc // 4, size=n_taps_bg)
        taps_bg[tap_indices_bg] = (rng.standard_normal(n_taps_bg) +
                                   1j * rng.standard_normal(n_taps_bg)) * 0.2
        self.h_bg_taps = taps_bg  # background in delay domain

        # For each RX antenna, apply a random phase/scale to background
        self.bg_rx_weights = (rng.standard_normal(self.nrx) +
                              1j * rng.standard_normal(self.nrx)) * 0.5

        # Target parameters
        self.target_base_tap = self.n_sc // 8  # starting delay tap
        self.target_amplitude = 1.0 + 0.0j
        self.target_speed = 0.2  # taps per second (moves in delay domain)

    def stop(self):
        self._running = False

    def stream(self) -> Generator[CSIFrame, None, None]:
        """
        Yield CSIFrame objects forever (until stop() is called).
        """
        while self._running:
            now = time.time()
            t_rel = now - self._t0

            # Simulated moving target delay tap index
            target_tap = self.target_base_tap + int(self.target_speed * t_rel) % (self.n_sc // 2)
            h_target_taps = np.zeros(self.n_sc, dtype=np.complex64)
            h_target_taps[target_tap] = self.target_amplitude

            # Total CIR taps per RX antenna = background + target
            # shape: [taps, nrx]
            h_taps = np.zeros((self.n_sc, self.nrx), dtype=np.complex64)
            for r in range(self.nrx):
                h_taps[:, r] = self.h_bg_taps * self.bg_rx_weights[r] + h_target_taps

            # Convert to frequency domain CSI by FFT
            # shape: [n_sc, nrx]
            H_f = np.fft.fft(h_taps, axis=0)

            # Add small noise
            noise = (np.random.standard_normal(H_f.shape) +
                     1j * np.random.standard_normal(H_f.shape)) * 0.01
            H_f_noisy = H_f + noise

            # Wrap into CSIFrame with n_sym = 1, ntx = 1
            csi = H_f_noisy[:, :, np.newaxis]  # [n_sc, nrx, 1]
            csi = csi[np.newaxis, ...]         # [1, n_sc, nrx, 1]

            frame = CSIFrame(
                timestamp=now,
                carrier_freq=self.carrier_freq,
                subcarrier_spacing=self.subcarrier_spacing,
                bandwidth=self.bandwidth,
                nrx=self.nrx,
                ntx=self.ntx,
                csi=csi.astype(np.complex64),
            )

            yield frame
            time.sleep(self.frame_interval)


class RealFiveGCSIStream:
    """
    Placeholder for a real 5G NIC / SDR integration.

    You would implement:
    - Connection to the 5G modem / SDR API
    - Retrieval of CSI for each reference signal opportunity (CSI-RS / PRS)
    - Construction of CSIFrame objects

    Currently this just raises NotImplementedError so you don't accidentally
    think it's doing hardware things :)
    """

    def __init__(self):
        raise NotImplementedError(
            "RealFiveGCSIStream must be implemented for your 5G hardware/API."
        )

    def stream(self) -> Generator[CSIFrame, None, None]:
        raise NotImplementedError


# ==========================
# Processing: CIR, background, presence
# ==========================

class BackgroundModel:
    """
    Simple running baseline model for CIR magnitude.
    Maintains a history window and returns (baseline, residual).
    """
    def __init__(self, max_history: int = 200):
        self.history = deque(maxlen=max_history)

    def update(self, cir_mag: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """
        cir_mag: np.ndarray [n_sym, n_taps, nrx]
        returns: (baseline, residual)
        """
        self.history.append(cir_mag)
        if len(self.history) < 10:
            baseline = cir_mag.copy()
        else:
            baseline = np.mean(np.stack(self.history, axis=0), axis=0)

        residual = cir_mag - baseline
        return baseline, residual


def cir_from_csi(frame: CSIFrame) -> np.ndarray:
    """
    Compute CIR (delay profile) magnitude from CSI.

    Args:
        frame: CSIFrame with csi.shape = [n_sym, n_sc, nrx, ntx]

    Returns:
        cir_mag: np.ndarray [n_sym, n_taps, nrx]
    """
    csi = frame.csi
    n_sym, n_sc, nrx, ntx = csi.shape
    assert ntx >= 1, "Need at least one TX antenna in CSI."

    cir_list = []
    for s in range(n_sym):
        # Use the first TX antenna (index 0) for simplicity
        H_sc = csi[s, :, :, 0]          # [n_sc, nrx]
        h_taps = np.fft.ifft(H_sc, axis=0)  # [n_sc, nrx]
        cir_list.append(h_taps)

    cir = np.stack(cir_list, axis=0)    # [n_sym, n_taps, nrx]
    cir_mag = np.abs(cir)
    return cir_mag


def presence_score(residual_cir_mag: np.ndarray) -> float:
    """
    Compute a simple scalar presence score from residual CIR magnitude.

    Args:
        residual_cir_mag: [n_sym, n_taps, nrx]

    Returns:
        scalar presence energy
    """
    return float(np.mean(np.abs(residual_cir_mag)))


# ==========================
# Visualization
# ==========================

class RangeTimePlot:
    """
    Live "range vs time" waterfall plot of residual CIR energy.

    - Y-axis: range bin (delay tap)
    - X-axis: time (scrolling)
    - Color: magnitude of residual CIR

    We reduce over RX antennas and OFDM symbols for a 2D map.
    """

    def __init__(self, n_taps: int, history_len: int = 200):
        self.n_taps = n_taps
        self.history_len = history_len
        self.buffer = deque(maxlen=history_len)  # each element: [n_taps]
        # initialize with zeros
        for _ in range(history_len):
            self.buffer.append(np.zeros(n_taps, dtype=float))

        # Matplotlib setup
        self.fig, self.ax = plt.subplots()
        self.img = self.ax.imshow(
            np.stack(self.buffer, axis=1),  # [n_taps, history_len]
            aspect='auto',
            origin='lower',
            interpolation='nearest'
        )
        self.ax.set_xlabel("Time (frames, most recent on the right)")
        self.ax.set_ylabel("Range bin (delay tap)")
        self.ax.set_title("Residual CIR Energy (Range-Time Waterfall)")
        self.fig.colorbar(self.img, ax=self.ax, label="Residual magnitude")

        # For graceful shutdown
        self._running = True

    def update(self, residual_cir_mag: np.ndarray):
        """
        residual_cir_mag: [n_sym, n_taps, nrx]
        Reduce over symbols and antennas to get [n_taps]
        """
        # mean over symbols + RX antennas
        rt = np.mean(residual_cir_mag, axis=(0, 2))  # [n_taps]
        self.buffer.append(rt)

    def draw(self):
        data = np.stack(self.buffer, axis=1)  # [n_taps, history_len]
        self.img.set_data(data)
        self.img.set_clim(vmin=np.min(data), vmax=np.max(data) + 1e-9)
        self.ax.set_xlim(0, data.shape[1] - 1)
        self.ax.set_ylim(0, data.shape[0] - 1)
        plt.pause(0.001)

    def stop(self):
        self._running = False


# ==========================
# Main loop
# ==========================

def run_scanner(simulate: bool = True):
    """
    Run the 5G room scanner in either simulation mode or real-hardware mode.
    """
    if simulate:
        stream = SimulatedFiveGCSIStream()
        print("[INFO] Running in SIMULATION mode.")
    else:
        stream = RealFiveGCSIStream()  # will raise NotImplementedError

    # Grab first frame to configure downstream sizes
    frame_iter = stream.stream()
    first_frame = next(frame_iter)
    cir_mag0 = cir_from_csi(first_frame)
    n_sym, n_taps, nrx = cir_mag0.shape

    bg = BackgroundModel(max_history=200)
    _, residual0 = bg.update(cir_mag0)

    rt_plot = RangeTimePlot(n_taps=n_taps, history_len=200)
    rt_plot.update(residual0)

    presence_hist = deque(maxlen=100)

    def producer():
        try:
            # We already consumed first_frame
            current_frame = first_frame
            while True:
                # Process current_frame
                cir_mag = cir_from_csi(current_frame)
                baseline, residual = bg.update(cir_mag)
                pscore = presence_score(residual)
                presence_hist.append(pscore)

                rt_plot.update(residual)

                # Print presence occasionally
                if len(presence_hist) == presence_hist.maxlen:
                    avg_presence = np.mean(presence_hist)
                    print(f"Presence score (avg over last {presence_hist.maxlen} frames): "
                          f"{avg_presence:.4f}", end="\r", flush=True)

                # Next frame
                current_frame = next(frame_iter)

        except StopIteration:
            pass
        except KeyboardInterrupt:
            pass
        finally:
            stream.stop()
            rt_plot.stop()
            print("\n[INFO] Stopping scanner.")

    # Run producer in a background thread so matplotlib main loop stays responsive
    thread = threading.Thread(target=producer, daemon=True)
    thread.start()

    # Matplotlib event loop
    try:
        while rt_plot._running:
            rt_plot.draw()
    except KeyboardInterrupt:
        pass
    finally:
        stream.stop()
        rt_plot.stop()
        print("\n[INFO] Exiting.")


def parse_args():
    parser = argparse.ArgumentParser(description="5G NIC-based room scanner (conceptual).")
    parser.add_argument(
        "--real",
        action="store_true",
        help="Use real 5G CSI stream instead of simulator (requires implementation)."
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run_scanner(simulate=not args.real)
