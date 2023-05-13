#!/usr/bin/env python3
# Copyright (c) 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import sys
from typing import Optional
from unittest import mock
from unittest import TestCase

from config import Project
import google.cloud.storage
import pytest

with mock.patch('google.cloud.storage'):
  import main  # pylint: disable=C0415

REVISION = "0123456789abcdef"

HTML_FILE = "demo.html"
UNICODE_FILE = "☕.jpg"
EMPTY_FILE = "empty.txt"
NO_EXTENSION = "jpg"
UNKNOWN_EXTENSION = "demo.invalid-extension"

INVALID_FILE = "invalid-file.txt"


def get_file_from_revision(revision: str, filename: str,
                           project: Project) -> Optional[bytes]:
  valid_filenames = {
      HTML_FILE,
      UNKNOWN_EXTENSION,
      UNICODE_FILE,
      NO_EXTENSION,
  }
  if filename in valid_filenames:
    return bytes(f"{filename}@{revision}", "utf-8")

  if filename == EMPTY_FILE:
    return b""

  return None


def flask_request():

  class Request:
    headers = {}

  return Request()


class DevtoolsFrontendServerTest(TestCase):

  @mock.patch('main.get_file_from_revision', side_effect=get_file_from_revision)
  def test_serve_rev(self, *mocks):  # pylint: disable=W0613
    with main.app.test_client() as c:
      # Happy path
      response = c.get(f"/serve_rev/@{REVISION}/{HTML_FILE}")
      self.assertEqual(response.status_code, 200)
      self.assertEqual(response.headers.get("Content-Type"), "text/html")
      self.assertEqual(response.data, bytes(f"{HTML_FILE}@{REVISION}", "utf-8"))

      # Unsupported / no extension returns as 'text/plain'
      response = c.get(f"/serve_rev/@{REVISION}/{UNKNOWN_EXTENSION}")
      self.assertEqual(response.status_code, 200)
      self.assertEqual(response.headers.get("Content-Type"), "text/plain")

      response = c.get(f"/serve_rev/@{REVISION}/{NO_EXTENSION}")
      self.assertEqual(response.status_code, 200)
      self.assertEqual(response.headers.get("Content-Type"), "text/plain")

      # Empty file
      response = c.get(f"/serve_rev/@{REVISION}/{EMPTY_FILE}")
      self.assertEqual(response.status_code, 200)
      self.assertEqual(response.headers.get("Content-Type"), "text/plain")
      self.assertEqual(response.data, b"")

      # Invalid file
      response = c.get(f"/serve_rev/@{REVISION}/{INVALID_FILE}")
      self.assertEqual(response.status_code, 404)

      # Unicode symbols
      response = c.get(f"serve_rev/@{REVISION}/{UNICODE_FILE}")
      self.assertEqual(response.status_code, 200)
      self.assertEqual(response.data,
                       bytes(f"{UNICODE_FILE}@{REVISION}", "utf-8"))

  def test_index(self):
    with main.app.test_client() as c:
      response = c.get("/")
      self.assertEqual(response.status_code, 200)


if __name__ == "__main__":
  sys.exit(pytest.main([__file__]))
