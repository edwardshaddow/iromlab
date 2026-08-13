#! /usr/bin/env python
"""Lightweight preferences dialog for Iromlab.

Two settings only:
  - rootDir           : where batches are saved
  - runFileExtraction : whether to extract ISO files after a batch

Saved to %APPDATA%\\iromlab\\prefs.json
"""

import os
import json
import tkinter as tk
from tkinter import filedialog as tkFileDialog
from tkinter import messagebox as tkMessageBox
from . import config


def _prefs_path():
    appdata   = os.environ.get("APPDATA", os.path.expanduser("~"))
    prefs_dir = os.path.join(appdata, "iromlab")
    os.makedirs(prefs_dir, exist_ok=True)
    return os.path.join(prefs_dir, "prefs.json")


def load_prefs():
    """Load saved prefs into config. Called after getConfiguration()
    so prefs can override rootDir from config.xml."""
    path = _prefs_path()
    if not os.path.isfile(path):
        return
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return
    if data.get("rootDir"):
        config.rootDir = os.path.normpath(data["rootDir"])
    if "runFileExtraction" in data:
        val = data["runFileExtraction"]
        if not isinstance(val, bool):
            val = str(val).lower() in ("true", "1", "yes")
        config.runFileExtraction = val


def save_prefs():
    data = {"rootDir": config.rootDir,
            "runFileExtraction": config.runFileExtraction}
    try:
        with open(_prefs_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
    except OSError as exc:
        tkMessageBox.showerror("Save error",
                               "Could not save preferences:\n{}".format(exc))


class PreferencesDialog(tk.Toplevel):

    def __init__(self, parent):
        super(PreferencesDialog, self).__init__(parent)
        self.title("Batch Preferences")
        self.resizable(False, False)
        self.grab_set()
        self.transient(parent)

        w, h = 440, 130
        px = parent.winfo_rootx() + (parent.winfo_width()  - w) // 2
        py = parent.winfo_rooty() + (parent.winfo_height() - h) // 2
        self.geometry("{}x{}+{}+{}".format(w, h, px, py))

        self._root_var    = tk.StringVar(value=config.rootDir)
        self._extract_var = tk.BooleanVar(value=config.runFileExtraction)
        self._build_ui()

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        row0 = tk.Frame(self)
        row0.pack(fill="x", **pad)
        tk.Label(row0, text="Batch save path:", width=14,
                 anchor="w").pack(side="left")
        tk.Entry(row0, textvariable=self._root_var,
                 width=32).pack(side="left", padx=(0, 4))
        tk.Button(row0, text="...", width=3,
                  command=self._browse).pack(side="left")

        row1 = tk.Frame(self)
        row1.pack(fill="x", padx=10, pady=2)
        tk.Checkbutton(
            row1,
            text="Extract files from ISO images",
            variable=self._extract_var
        ).pack(side="left")
 
# Extract MP4s from DVDs using Handbrake - WIP 
#        row2 = tk.Frame(self)
#        row2.pack(fill="x", padx=10, pady=2)
#        tk.Checkbutton(
#            row2,
#            text="Create MP4s from DVDs",
#            variable=self._extractDvd_var
#        ).pack(side="left")

        btn_row = tk.Frame(self)
        btn_row.pack(fill="x", padx=10, pady=(8, 10))
        tk.Button(btn_row, text="Save", width=10,
                  command=self._on_save).pack(side="right", padx=(4, 0))
        tk.Button(btn_row, text="Cancel", width=10,
                  command=self.destroy).pack(side="right")

    def _browse(self):
        path = tkFileDialog.askdirectory(
            title="Select batch save directory", mustexist=False)
        if path:
            self._root_var.set(os.path.normpath(path))

    def _on_save(self):
        new_root = self._root_var.get().strip()
        if not new_root:
            tkMessageBox.showerror("Error", "Batch save path cannot be empty")
            return
            
        config.rootDir           = os.path.normpath(new_root)
        config.runFileExtraction = self._extract_var.get()
#        config.runFileExtraction = self._extractDvd_var.get()
        save_prefs()
        self.destroy()
