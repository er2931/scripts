"""
tesseract_trig_handles.py
-------------------------

A collection of trigonometric, complex, and oscillatory optimization handles
for parallel training of the Tesseract system.

These functions are designed to:

- Add sinusoidal, oscillatory, and rotational dynamics into training.
- Provide minimization and maximization handles using trigonometric sweeps.
- Enable parallel multi-phase training using harmonic decomposition.
- Support complex-valued activation and response modeling.
- Provide 4D rotational trigonometric kernels.

This module assumes:
    from tesseract_system import Tesseract
"""

import numpy as np

# -------------------------------------------------------------
# 1. TRIGONOMETRIC OPTIMIZATION HANDLES
# -------------------------------------------------------------

def trig_scan_max(t: "Tesseract", active, steps=360):
    """
    Sweep θ from 0..2π and compute response amplitude.

    Returns:
        (best_theta, max_response_vector, max_index)
    """
    active = np.array(active, dtype=np.int32)
    num = t.num_nodes

    # base activation
    x = np.zeros(num, dtype=np.float32)
    x[active] = 1.0

    best_val = -1e18
    best_theta = 0
    best_y = None

    for k in range(steps):
        theta = 2 * np.pi * (k / steps)

        # oscillatory projection
        osc = np.sin(theta) * x + np.cos(theta) * x

        y = t.weights @ osc
        val = np.max(y)

        if val > best_val:
            best_val = val
            best_theta = theta
            best_y = y.copy()

    return best_theta, best_y, int(np.argmax(best_y))


def trig_scan_min(t: "Tesseract", active, steps=360):
    """
    Same as trig_scan_max but for minima.
    """
    active = np.array(active, dtype=np.int32)
    num = t.num_nodes

    x = np.zeros(num, dtype=np.float32)
    x[active] = 1.0

    best_val = 1e18
    best_theta = 0
    best_y = None

    for k in range(steps):
        theta = 2 * np.pi * (k / steps)

        osc = np.sin(theta) * x + np.cos(theta) * x

        y = t.weights @ osc
        val = np.min(y)

        if val < best_val:
            best_val = val
            best_theta = theta
            best_y = y.copy()

    return best_theta, best_y, int(np.argmin(best_y))


# -------------------------------------------------------------
# 2. COMPLEX TRIGONOMETRIC TRAINING
# -------------------------------------------------------------

def complex_phase_training(t: "Tesseract", active, lr=0.01, cycles=8):
    """
    Use a complex exponential kernel e^{iθ} to train with oscillatory phase shifts.

    This effectively rotates the activation pattern through complex-space,
    accumulating harmonics that reinforce multi-angle structure.

    Parallelizable: each cycle is independent.
    """
    active = np.array(active, dtype=np.int32)
    num = t.num_nodes

    # base vector
    x = np.zeros(num, dtype=np.complex128)
    x[active] = 1 + 0j

    for k in range(cycles):
        theta = 2 * np.pi * (k / cycles)

        # complex rotation
        phase = np.exp(1j * theta)
        z = x * phase

        # real + imaginary reinforcement
        t.weights += lr * (np.outer(z.real, z.real) +
                           np.outer(z.imag, z.imag)) * t.allowed_mask


# -------------------------------------------------------------
# 3. 4D ROTATION TRIGONOMETRY
# -------------------------------------------------------------
# 4D rotations require pairs of axes: (x,y,z,w)

def rotate_4d(vec, theta, plane=(0,1)):
    """
    Rotate a vector in 4D along any plane (i,j).

    vec: array of shape (4,)
    plane: tuple of axes to rotate
    """
    vec = vec.astype(np.float64)

    i, j = plane
    out = vec.copy()

    c = np.cos(theta)
    s = np.sin(theta)

    xi = vec[i]
    xj = vec[j]

    out[i] = c*xi - s*xj
    out[j] = s*xi + c*xj

    return out


def embed_4d_rotation(t: "Tesseract", idx, lr=0.01, rotations=16):
    """
    Treat the tesseract index (0..4095) as a 4D coordinate,
    rotate it through 4D planes, and reinforce those harmonic relationships.
    """
    if t.n != 64:
        raise ValueError("4D operations require n=64")

    a, b, c, d = t.coords4(idx)
    base_vec = np.array([a, b, c, d], dtype=np.float64)

    planes = [(0,1), (0,2), (0,3), (1,2), (1,3), (2,3)]

    for plane in planes:
        for k in range(rotations):
            theta = 2*np.pi*(k/rotations)

            v = rotate_4d(base_vec, theta, plane)

            # map rotated vector back to node-space
            a2 = int(np.clip(round(v[0]),0,7))
            b2 = int(np.clip(round(v[1]),0,7))
            c2 = int(np.clip(round(v[2]),0,7))
            d2 = int(np.clip(round(v[3]),0,7))

            j = t.idx4(a2,b2,c2,d2)

            if t.allowed_mask[idx,j]:
                t.weights[idx,j] += lr
                t.weights[j,idx] += lr


# -------------------------------------------------------------
# 4. PARALLEL TRAINING VIA HARMONIC DECOMPOSITION
# -------------------------------------------------------------

def harmonic_parallel_train(t: "Tesseract", activations, harmonics=6, lr=0.01):
    """
    Perform parallel harmonic decomposition:

        x_k = sin(kθ)x + cos(kθ)x

    Each harmonic trains independently and can be distributed in parallel.
    """
    activations = np.array(activations, dtype=np.int32)
    num = t.num_nodes

    base = np.zeros(num, dtype=np.float32)
    base[activations] = 1.0

    for k in range(1, harmonics+1):
        theta = 2*np.pi*(k/harmonics)
        x = np.sin(theta)*base + np.cos(theta)*base

        t.weights += lr * np.outer(x, x) * t.allowed_mask


# -------------------------------------------------------------
# 5. ENERGY-BASED TRIGONOMETRIC EVALUATOR
# -------------------------------------------------------------

def oscillatory_energy(t: "Tesseract", active, steps=180):
    """
    Compute the total oscillatory energy:

    E = Σθ || W @ (sinθ x + cosθ x) ||²

    Useful for detecting resonant directions.
    """
    active = np.array(active, dtype=np.int32)
    num = t.num_nodes

    x = np.zeros(num, dtype=np.float32)
    x[active] = 1.0

    total_energy = 0.0

    for k in range(steps):
        theta = 2*np.pi*(k/steps)
        u = np.sin(theta)*x + np.cos(theta)*x

        y = t.weights @ u
        total_energy += np.dot(y, y)

    return total_energy
