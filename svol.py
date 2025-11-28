# -----------------------------------------
# INSTANT WINDOWS VOLUME PRESET SCRIPT
# Try Windows Run (Win + R)
# -----------------------------------------
# Default value (will be overridden by input)
TARGET_VOLUME = 50  # 0–100
# -----------------------------------------

import platform

def set_system_volume(percent: int):
    if platform.system() != "Windows":
        return  # silently ignore on other OS

    from pycaw.pycaw import AudioUtilities

    device = AudioUtilities.GetSpeakers()
    volume = device.EndpointVolume  # new pycaw API

    # Convert to scalar (0.0–1.0)
    scalar = max(0.0, min(1.0, percent / 100.0))
    volume.SetMasterVolumeLevelScalar(scalar, None)

def main():
    global TARGET_VOLUME

    # Added input
    try:
        user_val = input("Enter volume (0–100): ").strip()
        TARGET_VOLUME = int(user_val)
    except:
        print("Invalid number.")
        return

    try:
        set_system_volume(TARGET_VOLUME)
    except:
        pass

if __name__ == "__main__":
    main()

