#!/usr/bin/env python3
# Copyright (c) 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import Optional, Union

from google.api_core.exceptions import NotFound
from google.api_core.exceptions import PreconditionFailed
from google.cloud.storage import Blob
from google.cloud.storage import Bucket


def download_blob(bucket: Bucket, blobname: str) -> Optional[bytes]:
  try:
    return bucket.blob(blobname).download_as_bytes()
  except NotFound:
    return None


def upload_from_string(blob: Blob, content: Union[str, bytes]):
  """Upload string or byte content, but do not override any existing data and
  fail silently."""
  try:
    blob.upload_from_string(content, if_generation_match=0)
  except PreconditionFailed as ex:
    if any(e['reason'] == 'conditionNotMet' and e['location'] == 'If-Match'
           for e in ex.response.json()['error']['errors']):
      return

    raise ex
