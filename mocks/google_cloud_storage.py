#!/usr/bin/env python3
# Copyright (c) 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from typing import Optional, Union

from google.api_core.exceptions import NotFound


class MockedBlob:

  def __init__(self,
               bucket: Optional['MockedBucket'],
               blob_name: Optional[str],
               exists: bool = True):
    self._download_as_bytes_count = 0
    self.bucket = bucket
    self.blob_name = blob_name
    self.byte_content = None
    self._exists = exists

  @classmethod
  def from_content(cls, byte_content: bytes) -> 'MockedBlob':
    blob = cls(None, None)
    blob.byte_content = byte_content
    return blob

  def upload_from_string(self,
                         content: Union[str, bytes],
                         if_generation_match=None) -> None:  # pylint: disable=W0613
    if isinstance(content, str):
      content = content.encode("utf-8")

    self.byte_content = content
    self.bucket.blobs[self.blob_name] = self
    self._exists = True

  def download_as_bytes(self) -> bytes:
    if not self._exists:
      raise NotFound("404 GET No mocked blob")
    self._download_as_bytes_count += 1
    return self.byte_content


class MockedBucket:

  def __init__(self, initial_blobs=None):
    self.blobs = initial_blobs or {}

  def blob(self, name: str) -> MockedBlob:
    if name in self.blobs:
      return self.blobs[name]

    return MockedBlob(self, name, exists=False)
