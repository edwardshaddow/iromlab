#! /usr/bin/env python
"""
Global configuration state for Iromlab.
All values are defaults; getConfiguration() in iromlab.py overwrites them from config.xml at startup.
"""

# Application
version = ""

# Batch state (runtime only)
batchFolder      = ""
batchManifest    = ""
jobsFolder       = ""
jobsFailedFolder = ""
quitFlag         = False
batchIsOpen      = False
readyToStart     = False
finishedBatch    = False

# General
prefixBatch       = ""
rootDir           = ""
tempDir           = ""
secondsToTimeout  = ""
audioFormat       = ""

# Robot
driverScript  = ""
cdDriveLetter = ""
comPort       = "COM1" # default for Cronus
comSpeed      = "9600" # default for Cronus

# Executable paths
prebatchExe            = ""
loadExe                = ""
unloadExe              = ""
rejectExe              = ""
isoBusterExe           = ""
dBpowerampConsoleRipExe = ""
shntoolExe             = ""
flacExe                = ""
cdInfoExe              = ""

# Processing
extractAudio       = False
runFileExtraction  = False
enablePPNLookup    = True
enableSocketAPI    = False
startOnFinalize    = False

# Network
socketHost = "127.0.0.1"
socketPort = "65432"

# IsoBuster report format
reportFormatString = ""
