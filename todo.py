import tkinter as tk
from tkinter import messagebox
import json
import os

# File to store tasks
TASK_FILE = "tasks.json"

class TodoApp:
    def __init__(self, root):
        self.root = root
        self.root.title("To-Do List Manager")
        self.root.geometry("400x500")
        self.root.resizable(False, False)

        self.tasks = []
        self.load_tasks()

        # ----- UI Layout -----
        tk.Label(root, text="To-Do List", font=("Helvetica", 18, "bold")).pack(pady=10)

        self.task_entry = tk.Entry(root, font=("Helvetica", 14))
        self.task_entry.pack(padx=10, pady=5, fill=tk.X)
        self.task_entry.bind("<Return>", lambda e: self.add_task())

        button_frame = tk.Frame(root)
        button_frame.pack(pady=5)

        tk.Button(button_frame, text="Add", width=10, command=self.add_task).grid(row=0, column=0, padx=5)
        tk.Button(button_frame, text="Delete", width=10, command=self.delete_task).grid(row=0, column=1, padx=5)
        tk.Button(button_frame, text="Clear All", width=10, command=self.clear_all).grid(row=0, column=2, padx=5)

        self.listbox = tk.Listbox(root, font=("Helvetica", 13), height=18, selectmode=tk.SINGLE)
        self.listbox.pack(padx=10, pady=10, fill=tk.BOTH)
        self.populate_listbox()

        tk.Button(root, text="Save Tasks", command=self.save_tasks, width=20).pack(pady=10)

        # Bind double-click to mark complete/incomplete
        self.listbox.bind("<Double-Button-1>", self.toggle_complete)

    # ----- Core Functions -----
    def add_task(self):
        task_text = self.task_entry.get().strip()
        if not task_text:
            messagebox.showwarning("Warning", "Please enter a task.")
            return

        self.tasks.append({"task": task_text, "done": False})
        self.task_entry.delete(0, tk.END)
        self.populate_listbox()
        self.save_tasks()

    def delete_task(self):
        selection = self.listbox.curselection()
        if not selection:
            messagebox.showwarning("Warning", "Select a task to delete.")
            return
        index = selection[0]
        del self.tasks[index]
        self.populate_listbox()
        self.save_tasks()

    def clear_all(self):
        if messagebox.askyesno("Confirm", "Delete all tasks?"):
            self.tasks.clear()
            self.populate_listbox()
            self.save_tasks()

    def toggle_complete(self, event):
        selection = self.listbox.curselection()
        if not selection:
            return
        index = selection[0]
        self.tasks[index]["done"] = not self.tasks[index]["done"]
        self.populate_listbox()
        self.save_tasks()

    # ----- File Handling -----
    def save_tasks(self):
        with open(TASK_FILE, "w") as f:
            json.dump(self.tasks, f, indent=2)
        print("Tasks saved.")

    def load_tasks(self):
        if os.path.exists(TASK_FILE):
            with open(TASK_FILE, "r") as f:
                self.tasks = json.load(f)

    # ----- UI Update -----
    def populate_listbox(self):
        self.listbox.delete(0, tk.END)
        for t in self.tasks:
            text = f"✔ {t['task']}" if t["done"] else t["task"]
            self.listbox.insert(tk.END, text)
            if t["done"]:
                self.listbox.itemconfig(tk.END, fg="gray")
            else:
                self.listbox.itemconfig(tk.END, fg="black")


if __name__ == "__main__":
    root = tk.Tk()
    app = TodoApp(root)
    root.mainloop()
