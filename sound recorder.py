import soundcard as sc
import soundfile as sf
import numpy as np

SAMPLE_RATE = 44100
BLOCKSIZE = 2048
OUT_FILE = "monitor_audio.wav"

# Find a loopback device (records speaker output)
mics = sc.all_microphones(include_loopback=True)
loopbacks = [m for m in mics if m.isloopback]

if not loopbacks:
    print("[!] No loopback / monitor devices found.")
    print("    On Windows, make sure your sound driver exposes a 'Stereo Mix' or loopback device.")
    raise SystemExit(1)

# Prefer loopback that matches default speaker, else first one
default_speaker = sc.default_speaker()
print("Default speaker:", default_speaker.name)

loopback = None
for m in loopbacks:
    if default_speaker.name.split('(')[0].strip() in m.name:
        loopback = m
        break
if loopback is None:
    loopback = loopbacks[0]

print("Using loopback device:", loopback.name)

frames = []

try:
    with loopback.recorder(samplerate=SAMPLE_RATE, blocksize=BLOCKSIZE) as rec:
        print("Recording monitor audio... Press CTRL+C to stop.")
        while True:
            data = rec.record(numframes=BLOCKSIZE)
            frames.append(data)
except KeyboardInterrupt:
    print("\nStopping recording...")

if frames:
    audio = np.concatenate(frames, axis=0)
    sf.write(OUT_FILE, audio, SAMPLE_RATE)
    print("Saved to", OUT_FILE)
else:
    print("[!] No audio captured.")
