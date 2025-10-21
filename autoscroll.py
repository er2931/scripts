import pyautogui
import keyboard
import time

def main():
    print("Auto scroll started.")
    print("Press '+' to increase speed, '-' to decrease speed, and 'q' to quit.\n")

    scroll_speed = 1  # How many "scroll units" per tick
    delay = 0.1       # Delay between scrolls

    while True:
        if keyboard.is_pressed('q'):
            print("Exiting...")
            break

        # Adjust speed with keys
        if keyboard.is_pressed('+'):
            scroll_speed += 1
            print(f"Speed increased to {scroll_speed}")
            time.sleep(0.3)

        elif keyboard.is_pressed('-') and scroll_speed > 1:
            scroll_speed -= 1
            print(f"Speed decreased to {scroll_speed}")
            time.sleep(0.3)

        # Scroll down (negative value = scroll down)
        pyautogui.scroll(-scroll_speed)
        time.sleep(delay)

if __name__ == "__main__":
    main()
