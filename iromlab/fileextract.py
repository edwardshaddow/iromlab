#! /usr/bin/env python
"""Post-batch ISO file extraction using IsoBuster.
Called as a module function from cdworker.py.
"""

import os
import subprocess
import logging
from datetime import datetime


def extractIsos(isoDirectory, isobusterPath):
    """ Extracts files in ISOs created by Isobuster """
    
    if not isoDirectory or not os.path.isdir(isoDirectory):
        # Checking for the right folder location
        logging.error("fileExtract: invalid directory: {}".format(isoDirectory))
        return

    if not isobusterPath or not os.path.isfile(isobusterPath):
        # Checking IsoBuster is available
        logging.error("fileExtract: IsoBuster not found at {}".format(isobusterPath))
        return

    error_log = os.path.join(isoDirectory, "IsoExtractionErrors.log")
    isoFiles = []

    for root, _, files in os.walk(isoDirectory):
        # Looks for all ISO files in folder
        for fname in files:
            if fname.lower().endswith(".iso"):
                isoFiles.append(os.path.join(root, fname))

    if not isoFiles:
        logging.info("fileExtract: no ISO files found")
        return

    logging.info("fileExtract: found {} ISO file(s)".format(len(isoFiles)))

    for isoPath in isoFiles:
        # Creates a folder for each ISO to extract into
        isoFolder = os.path.dirname(isoPath)
        baseName  = os.path.splitext(os.path.basename(isoPath))[0]
        outputDir = os.path.join(isoFolder, baseName)
        os.makedirs(outputDir, exist_ok=True)

        logging.info("fileExtract: extracting {}".format(os.path.basename(isoPath)))

        # CLI command for Isobuster to extract files
        args = [isobusterPath, isoPath,
                "/ef:" + outputDir,
                "/et:u", "/ep:oea", "/ep:owr", "/ep:npc",
                "/nosplash", "/m", "/c"]
        try:
            subprocess.run(args, check=True)
            logging.info("fileExtract: completed {}".format(
                os.path.basename(isoPath)))
        except subprocess.CalledProcessError as exc:
            msg = "[{}] ERROR extracting '{}': {}\n".format(
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"), isoPath, exc)
            logging.error(msg.strip())
            try:
                with open(error_log, "a", encoding="utf-8") as fh:
                    fh.write(msg)
            except OSError:
                pass

    logging.info("fileExtract: extraction complete")
    
# def extractDvd(isoDirectory, isobusterPath):
    """ Extracts video files in DVD ISOs created by Isobuster as MP4s - WIP """
