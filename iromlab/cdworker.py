#! /usr/bin/env python
"""This module contains iromlab's cdWorker code, i.e. the code that monitors
the list of jobs (submitted from the GUI) and does the actual imaging and ripping
"""

import os
import shutil
import time
import glob
import csv
import hashlib
import stat
import logging
import importlib
import _thread as thread
import pythoncom
import wmi
from . import config
from . import cdinfo
from . import isobuster
from . import dbpoweramp
from . import verifyaudio
from . import mdo
from . import fileExtract

# ── Load Nimbie/Cronus Drivers ────────────────────────────────────────────────────────────

def _loadDriver():
    """ Sets the drivers to the machine type indicated in the config XML """
    script = getattr(config, "driverScript", "Nimbie")
    if script == "Nimbie":
        return importlib.import_module(".drivers_nimbie", package=__package__)
    elif script == "Cronus":
        return importlib.import_module(".drivers_cronus", package=__package__)
    else:
        raise ValueError("Unknown driverScript: {}".format(script))

# ── Disc Classifications ───────────────────────────────────────────────────────

AUDIO_ONLY     = "AUDIO_ONLY" # Will rip audio via dBpoweramp
DATA_SINGLE    = "DATA_SINGLE" # Will create an ISO via IsoBuster
DATA_MULTI     = "DATA_MULTI" # Will create a BIN/CUE via IsoBuster
DVD            = "DVD" # Will create an ISO via IsoBuster
CD_EXTRA       = "CD_EXTRA" # Will rip session 1 audio via dBpoweramp and create ISO of session 2 via IsoBuster
MIXED_MODE     = "MIXED_MODE" # Will create a Raw2User Data ISO/CUE via IsoBuster
CD_INTERACTIVE = "CD_INTERACTIVE" # Will create a RAW BIN/ISO via IsoBuster
BLANK          = "BLANK" # Regjects blank disk
UNKNOWN        = "UNKNOWN" # Regjects unknown disk


def classifyDisc(ci):
    if ci.get("cdInteractive"):    return CD_INTERACTIVE
    if ci.get("cdExtra"):          return CD_EXTRA
    if ci.get("mixedMode"):        return MIXED_MODE
    if ci.get("containsAudio") and not ci.get("containsData"): return AUDIO_ONLY
    if ci.get("containsData")  and not ci.get("containsAudio"):
        return DATA_MULTI if ci.get("multiSession") else DATA_SINGLE
    if not ci.get("containsAudio") and not ci.get("containsData"): return BLANK
    return UNKNOWN

# ── Helpers ───────────────────────────────────────────────────────────────────

def mediumLoaded(driveName):
    """Returns True if medium is loaded (also if blank/unredable), False if not"""

    # Use CoInitialize to avoid errors like this:
    # http://stackoverflow.com/questions/14428707/python-function-is-unable-to-run-in-new-thread
    pythoncom.CoInitialize()
    c = wmi.WMI()
    foundDriveName = False
    loaded = False
    for cdrom in c.Win32_CDROMDrive():
        if cdrom.Drive == driveName:
            foundDriveName = True
            loaded = cdrom.MediaLoaded

    return(foundDriveName, loaded)

def generate_file_md5(fileIn):
    """Generate MD5 hash of file"""

    # fileIn is read in chunks to ensure it will work with (very) large files as well
    # Adapted from: http://stackoverflow.com/a/1131255/1209004

    blocksize = 2**20
    m = hashlib.md5()
    with open(fileIn, "rb") as f:
        while True:
            buf = f.read(blocksize)
            if not buf:
                break
            m.update(buf)
    return m.hexdigest()

def generate_file_sha512(file_in, retries=10, wait=5):
    """Generate sha512 hash of file"""
    
    # fileIn is read in chunks to ensure it will work with (very) large files as well
    # Adapted from: http://stackoverflow.com/a/1131255/1209004
    
    # Added folder locked error logging and retries
    
    blocksize = 2**20
    for attempt in range(retries):
        try:
            m = hashlib.sha512()
            with open(file_in, "rb") as fh:
                while True:
                    buf = fh.read(blocksize)
                    if not buf:
                        break
                    m.update(buf)
            return m.hexdigest()
        except PermissionError:
            logging.warning("SHA-512: locked, retry {}/{} in {}s".format(
                attempt + 1, retries, wait))
            time.sleep(wait)
    logging.error("SHA-512: failed after {} attempts: {}".format(retries, file_in))
    return None

def _unlockFolder(folderPath):
    """Fixes file permission errors for fixity check"""
    
    for root, dirs, files in os.walk(folderPath):
        for name in files:
            try:
                os.chmod(os.path.join(root, name), stat.S_IWRITE)
            except OSError:
                pass

def checksumDirectory(directory):
    """Calculate checksums for all files in directory"""
    
    # All files in directory
    _unlockFolder(directory)
    allFiles = [f for f in glob.glob(os.path.join(directory, "*"))
                 if os.path.isfile(f)]
                 
    # Dictionary for storing results
    checksums = {}

    for fName in allFiles:
        hashString = generate_file_sha512(fName)
        checksums[fName] = hashString

    # Write checksum file
    try:
        fChecksum = open(os.path.join(directory, "checksums.sha512"), "w", encoding="utf-8")
        for fName in checksums:
            lineOut = checksums[fName] + " " + os.path.basename(fName) + '\n'
            fChecksum.write(lineOut)
        fChecksum.close()
        wroteChecksums = True
    except IOError:
        wroteChecksums = False

    return wroteChecksums

# ── Audio ripping workflow ─────────────────────────────────────────────────────────────

def _ripAudio(dirDisc, success, reject):
    logging.info("*** Ripping audio ***")
    result = dbpoweramp.consoleRipper(dirDisc)
    # Rip audio using dBpoweramp console ripper
    logging.info("dBpoweramp command: {}".format(result["cmdStr"]))
    logging.info("dBpoweramp status:  {}".format(result["status"]))
    logging.info("dBpoweramp log:\n{}".format(result["log"]))

    if str(result["status"]) != "0":
        success = False
        reject = True
        logging.error("dBpoweramp exited with error(s)")

    # Verify that created audio files are not corrupt (using shntool / flac)
    logging.info("*** Verifying audio ***")
    audioHasErrors, audioErrorsList = verifyaudio.verifyCD(dirDisc, config.audioFormat)
    logging.info(''.join(['audioHasErrors: ', str(audioHasErrors)]))
    
    if audioHasErrors:
        success = False
        reject = True
        logging.error("Audio verification returned error(s)")

    return success, reject


# ── IsoBuster result checks ───────────────────────────────────────────────────
    """Organises logging for disc processing actions"""

def _checkIso(result, success, reject):
    logging.info("isobuster command:   {}".format(result["cmdStr"]))
    logging.info("isobuster status:    {}".format(result["status"]))
    logging.info("volumeIdentifier:    {}".format(result["volumeIdentifier"]))
    logging.info("isolyzerSuccess:     {}".format(result["isolyzerSuccess"]))
    logging.info("imageTruncated:      {}".format(result["imageTruncated"]))

    if result["log"].strip() != "0":
        success = False
        reject = True
        logging.error("IsoBuster exited with error(s)")
    elif not result["isolyzerSuccess"]:
        success = False
        reject = True
        logging.error("Isolyzer reported failure")
    elif result["imageTruncated"]:
        success = False
        reject = True
        logging.error("Isolyzer detected truncated image")
    return success, reject


def _checkBincue(result, success, reject):
    logging.info("isobuster command: {}".format(result["cmdStr"]))
    logging.info("isobuster status:  {}".format(result["status"]))
    if result["log"].strip() != "0":
        success = False
        reject = True
        logging.error("IsoBuster exited with error(s) during BIN/CUE extraction")
    return success, reject


# ── Disc processing ───────────────────────────────────────────────────────────

def processDisc(carrierData, drivers):
    """Process one disc / job based on disc classification"""
    
    jobID = carrierData['jobID']
    PPN = carrierData['PPN']
    title = carrierData["title"]
    volumeNo = carrierData["volumeNo"]
    
    logging.info(''.join(['### Job: ', jobID]))
    logging.info(''.join(['PPN: ', carrierData['PPN']]))
    logging.info(''.join(['Title: ', carrierData['title']]))
    logging.info(''.join(['Volume number: ', carrierData['volumeNo']]))

    # Initialise status and disc type
    reject = False
    success = True
    discType = UNKNOWN
    carrierInfo = {
        "containsAudio": False, "containsData": False,
        "cdExtra": False, "mixedMode": False,
        "cdInteractive": False, "multiSession": False,
    }
    resultIsobuster = None

    # Create output folder for this disc
    dirDisc = os.path.join(config.batchFolder, jobID)
    logging.info(''.join(['disc directory: ', dirDisc]))
    if not os.path.exists(dirDisc):
        os.makedirs(dirDisc)

    # Load disc
    logging.info('*** Loading disc ***')
    resultLoad = drivers.load()
    logging.info(''.join(['load command: ', resultLoad['cmdStr']]))
    logging.info(''.join(['load command output: ', resultLoad['log'].strip()]))

    # Test if disc is loaded
    discLoaded = False

    # Reject if no CD is found after 20 s
    timeout = time.time() + int(config.secondsToTimeout)
    while not discLoaded and time.time() < timeout:
        # Timeout value prevents infinite loop in case of unreadable disc
        time.sleep(2)
        foundDrive, discLoaded = mediumLoaded(config.cdDriveLetter + ":")

    if not foundDrive:
        success = False
        logging.error(''.join(['drive ', config.cdDriveLetter, ' does not exist']))

    if not discLoaded:
        success = False
      # reject = True
        resultReject = drivers.reject()
        logging.error("No disc loaded within timeout")
        logging.info(''.join(['reject command: ', resultReject['cmdStr']]))
        logging.info(''.join(['reject command output: ', resultReject['log'].strip()]))
        
        # !!IMPORTANT!!: we can end up here b/c of 2 situations:
        #
        # 1. No disc was loaded (b/c loader was empty at time 'load' command was run
        # 2. A disc was loaded, but it is not accessable (badly damaged disc)
        #
        # In production env. where ech disc corresponds to a catalog identifier in a
        # queue, 1. can simply be ignored (keep trying to load another disc, once disc
        # is loaded it can be linked to next catalog identifier in queue). However, in case
        # 2. the failed disc corresponds to the next identifier in the queue! So somehow
        # we need to distinguish these cases in order to keep discs in sync with identifiers!
        #
        # UPDATE: Case 1. can be eliminated if loading of a CD is made dependent of
        # a queue of disc ids (which are entered by operator at time of adding a CD)
        #
        # In that case:
        #
        # queue is empty --> no CD in loader --> pause loading until new item in queue
        #
        # (Can still go wrong if items are entered in queue w/o loading any CDs, but
        # this is an edge case)

    else:
        # Get disc info and define disc type
        logging.info("*** Running cd-info ***")
        carrierInfo = cdinfo.getCarrierInfo(dirDisc)
        logging.info("containsAudio:  {}".format(carrierInfo["containsAudio"]))
        logging.info("containsData:   {}".format(carrierInfo["containsData"]))
        logging.info("cdExtra:        {}".format(carrierInfo["cdExtra"]))
        logging.info("mixedMode:      {}".format(carrierInfo["mixedMode"]))
        logging.info("cdInteractive:  {}".format(carrierInfo["cdInteractive"]))
        logging.info("multiSession:   {}".format(carrierInfo["multiSession"]))

        discType = classifyDisc(carrierInfo)
        logging.info("Disc type: {}".format(discType))

        # Process by disc type
        if discType == AUDIO_ONLY:
            # Rip audio using dBpoweramp console ripper
            if config.extractAudio:
                success, reject = _ripAudio(dirDisc, success, reject)
            else:
                logging.info("Audio extraction disabled — skipping audio disc")

        elif discType == DATA_SINGLE:
            logging.info("*** Extracting single-session data to ISO ***")
            # Create ISO image of first session
            resultIsobuster = isobuster.extractData(dirDisc, 1, 0)
            success, reject = _checkIso(resultIsobuster, success, reject)

        elif discType == DATA_MULTI:
            logging.info("*** Extracting multi-session data to BIN/CUE ***")
            # Create Bin/Cue image of whole disc
            resultIsobuster = isobuster.extractRawData(dirDisc)
            success, reject = _checkBincue(resultIsobuster, success, reject)

        elif discType == DVD:
            logging.info("*** Extracting DVD to ISO ***")
            # Create ISO image of first session
            resultIsobuster = isobuster.extractData(dirDisc, 1, 0)
            success, reject = _checkIso(resultIsobuster, success, reject)

        elif discType == CD_EXTRA:
            # Rip audio using dBpoweramp console ripper
            if config.extractAudio:
                success, reject = _ripAudio(dirDisc, success, reject)
            logging.info("*** Extracting CD-Extra data session to ISO ***")
            lsn = int(carrierInfo.get("dataTrackLSNStart", 0))
            # Create ISO image of second session
            resultIsobuster = isobuster.extractData(dirDisc, 2, lsn)
            success, reject = _checkIso(resultIsobuster, success, reject)

        elif discType == MIXED_MODE:
            logging.info("*** Extracting mixed-mode disc to Raw2User ISO/CUE ***")
            # lsn = int(carrierInfo.get("dataTrackLSNStart", 0))
            # Create ISO/Cue image of whole disc
            resultIsobuster = isobuster.extractMixData(dirDisc)
            success, reject = _checkBincue(resultIsobuster, success, reject)

        elif discType == CD_INTERACTIVE:
            logging.info("*** Extracting CD-Interactive to raw image ***")
            # Extract data from CD-Interactive to raw image
            resultIsobuster = isobuster.extractRawData(dirDisc)
            if resultIsobuster["log"].strip() != "0":
                success     = False
                reject = True
                logging.error("IsoBuster error on CD-i disc")
        
        elif discType == BLANK:
            # Blank discs are rejected
            success     = False
            reject = True
            logging.warning("Blank disc — rejecting")
        
        else:
            # We end up here if cd-info wasn't able to identify the disc
            success = False
            reject = True
            logging.error("Unknown disc type — rejecting")
        
        # PPN metadata
        if config.enablePPNLookup:
            # Fetch metadata from KBMDO and store as file
            logging.info('*** Writing metadata from KB-MDO to file ***')

            successMdoWrite = mdo.writeMDORecord(PPN, dirDisc)
            if not successMdoWrite:
                success = False
                reject = True
                logging.error("Could not write metadata from KB-MDO")

        # Generate checksum file
        logging.info('*** Computing checksums ***')
        successChecksum = checksumDirectory(dirDisc)

        if not successChecksum:
            success = False
            reject = True
            logging.error("Writing checksum file failed")

        # Unload or reject disc
        if not reject:
            logging.info('*** Unloading disc ***')
            resultUnload = drivers.unload()
            logging.info(''.join(['unload command: ', resultUnload['cmdStr']]))
            logging.info(''.join(['unload command output: ', resultUnload['log'].strip()]))
        else:
            logging.info('*** Rejecting disc ***')
            resultReject = drivers.reject()
            logging.info(''.join(['reject command: ', resultReject['cmdStr']]))
            logging.info(''.join(['reject command output: ', resultReject['log'].strip()]))

    # Create comma-delimited batch manifest entry for this carrier

    volumeID = ""
    if resultIsobuster:
        volumeID = resultIsobuster.get("volumeIdentifier", "").strip()

    row = [jobID, PPN, volumeNo, title, volumeID,
           str(success),
           str(carrierInfo.get("containsAudio",   False)),
           str(carrierInfo.get("containsData",    False)),
           str(carrierInfo.get("cdExtra",         False)),
           str(carrierInfo.get("mixedMode",       False)),
           str(carrierInfo.get("cdInteractive",   False)),
           str(carrierInfo.get("multiSession",    False)),
           discType]

    try:
        with open(config.batchManifest, "a", encoding="utf-8", newline="") as bm:
            csv.writer(bm).writerow(row)
    except IOError as exc:
        logging.error("Could not write to batch manifest: {}".format(exc))

    return success

# ── Quit helper ───────────────────────────────────────────────────────────────

def quitIromlab():
    """Send KeyboardInterrupt after user pressed Exit button"""
    logging.info('*** Quitting because user pressed Exit ***')
    # Wait 2 seconds to avoid race condition between logging and KeyboardInterrupt
    time.sleep(2)
    # This triggers a KeyboardInterrupt in the main thread
    thread.interrupt_main()

# ── Main worker loop ──────────────────────────────────────────────────────────

def cdWorker():
    """Worker function that monitors the job queue and processes the discs in FIFO order"""

    drivers = _loadDriver()
    
    # Initialise 'success' flag to prevent run-time error in case user
    # finalizes batch before entering any carriers (edge case)
    success = True

    # Loop periodically scans value of config.batchFolder
    while not config.readyToStart:
        time.sleep(2)

    # Write Iromlab version to file in batch
    versionFile = os.path.join(config.batchFolder, 'version.txt')
    with open(versionFile, "w", encoding="utf-8") as vf:
        vf.write(config.version + "\n")

    # Define batch manifest (CSV file with minimal metadata on each carrier)
    config.batchManifest = os.path.join(config.batchFolder, 'manifest.csv')

    # Write header row if batch manifest doesn't exist already
    if not os.path.isfile(config.batchManifest):
        headerBatchManifest = (['jobID',
                                'PPN',
                                'volumeNo',
                                'title',
                                'volumeID',
                                'success',
                                'containsAudio',
                                'containsData',
                                'cdExtra',
                                'mixedMode',
                                'cdInteractive',
                                'multiSession',
                                'discType'])

        # Open batch manifest in append mode
        bm = open(config.batchManifest, "a", encoding="utf-8")

        # Create CSV writer object
        csvBm = csv.writer(bm, lineterminator='\n')

        # Write header to batch manifest and close file
        csvBm.writerow(headerBatchManifest)
        bm.close()

    # Initialise batch
    logging.info('*** Initialising batch ***')
    resultPrebatch = drivers.prebatch()
    logging.info(''.join(['prebatch command: ', resultPrebatch['cmdStr']]))
    logging.info(''.join(['prebatch command output: ', resultPrebatch['log'].strip()]))

    # Flag that marks end of batch (main processing loop keeps running while False)
    endOfBatchFlag = False

    # Check if user pressed Exit, and quit if so ...
    if config.quitFlag:
        quitIromlab()

    while not endOfBatchFlag and not config.quitFlag:
        time.sleep(2)

        # Get directory listing, sorted by creation time
        # List conversion because in Py3 a filter object is not a list!
        files = list(filter(os.path.isfile, glob.glob(config.jobsFolder + '/*')))
        files.sort(key=lambda x: os.path.getctime(x))

        noFiles = len(files)

        if noFiles > 0:
            # Identify oldest job file
            jobOldest = files[0]

            # Open job file and read contents
            fj = open(jobOldest, "r", encoding="utf-8")

            fjCSV = csv.reader(fj)
            jobList = next(fjCSV)
            fj.close()

            if jobList[0] == 'EOB':
                # End of current batch
                endOfBatchFlag = True
                config.readyToStart = False
                config.finishedBatch = True
                config.batchIsOpen = False
                os.remove(jobOldest)
                shutil.rmtree(config.jobsFolder)
                shutil.rmtree(config.jobsFailedFolder)
                logging.info('*** End Of Batch ***')

                if config.runFileExtraction:
                # Runs file extraction for ISO/BIN images if set in preferences
                    logging.info("*** Running post-batch file extraction ***")
                    fileExtract.extractIsos(config.batchFolder,
                                             config.isoBusterExe)
                    fileExtract.extractBins(config.batchFolder,
                                             config.isoBusterExe)
                    logging.info("*** File Extraction Complete ***")
                
                # Wait 2 seconds to avoid race condition between logging and KeyboardInterrupt
                time.sleep(2)
                # This triggers a KeyboardInterrupt in the main thread
                thread.interrupt_main()
            
            else:
                # Set up dictionary that holds carrier data
                carrierData = {}
                carrierData['jobID'] = jobList[0]
                carrierData['PPN'] = jobList[1]
                carrierData['title'] = jobList[2]
                carrierData['volumeNo'] = jobList[3]

                # Process the carrier
                success = processDisc(carrierData, drivers)
                #success = processDiscTest(carrierData)

            if success and not endOfBatchFlag:
                # Remove job file
                os.remove(jobOldest)
            elif not endOfBatchFlag:
                # Move job file to failed jobs folder
                baseName = os.path.basename(jobOldest)
                os.rename(jobOldest, os.path.join(config.jobsFailedFolder, baseName))

        # Check if user pressed Exit, and quit if so ...
        if config.quitFlag:
            quitIromlab()
