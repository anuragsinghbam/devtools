#!/usr/bin/env python3
# Copyright (c) 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import enum
import os

MAX_CACHE_AGE = 7 * 24 * 60 * 60

# TODO: Files are not yet verified via chrome-signed. The feature is tracked in
# https://crbug.com/1222968.
CHROME_UNSIGNED_BUCKET = "chrome-unsigned"
CHROME_UNSIGNED_ARTIFACT_PATH = "desktop-5c0tCh/%s/linux64/devtools-frontend.zip"
CHROME_UNSIGNED_DT_FRONTEND_ZIP_BASE_DIRS = [
    "devtools-frontend/gen/third_party/devtools-frontend-internal/devtools-frontend/front_end/",
]
CHROME_UNSIGNED_DT_INTERNAL_ZIP_BASE_DIRS = [
    "devtools-frontend/gen/third_party/devtools-frontend-internal/",
]

LEGACY_BUCKET = "chrome-devtools-frontend"

LOCAL_BUCKET = os.getenv("LOCAL_BUCKET")
IS_GAE = os.getenv("GAE_ENV") == "standard"


class Project(enum.Enum):
  DEVTOOLS_FRONTEND = "devtools-frontend"
  DEVTOOLS_INTERNAL = "devtools-internal"
