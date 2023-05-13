#!/usr/bin/env python3
# Copyright (c) 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import base64
import json
import sys
from unittest import mock
from unittest import TestCase

from mocks.google_cloud_storage import MockedBlob
from mocks.google_cloud_storage import MockedBucket
import pytest
import requests
import versions

VALID_6D_REVISION_NO_A = "1b8b78"
VALID_40D_REVISION_NO_A = "1b8b78f5838ed0b1c69bb4e51ea0252171854915"
VALID_40D_REVISION_NO_B = "2b8b78f5838ed0b1c69bb4e51ea0252171854915"
INVALID_REVISION_NO_1 = "a18b78f5838ed0b1c69bb4e51ea0252171854915"
INVALID_REVISION_NO_2 = "b18b78f5838ed0b1c69bb4e51ea0252171854915"
INVALID_REVISION_NO_3 = "c18b78f5838ed0b1c69bb4e51ea0252171854915"
INVALID_REVISION_NO_4 = "d18b78f5838ed0b1c69bb4e51ea0252171854915"

# Invalid digit
INVALID_REVISION_FORMAT_1 = "m18b78f5838ed0b1c69bb4e51ea0252171854915"

# Too short
INVALID_REVISION_FORMAT_2 = "12af"

# Too long
INVALID_REVISION_FORMAT_3 = "aa18b78f5838ed0b1c69bb4e51ea0252171854915"


class MockedResponse:

  def __init__(self, raw_response, status_code):
    self._raw = raw_response
    self.status_code = status_code

  def json(self):
    return json.loads(self._raw)

  @property
  def content(self):
    return self._raw


class IsValidVersionTest(TestCase):

  def test_valid_versions(self):
    self.assertTrue(versions.is_valid_version("1.0.1.0"))
    self.assertTrue(versions.is_valid_version("35.12.2011.19"))

  def test_invalid_versions(self):
    self.assertFalse(versions.is_valid_version("0.12.2011.19"))  # Major is 0
    self.assertFalse(versions.is_valid_version("35.12.0.19"))  # Patch is 0
    self.assertFalse(versions.is_valid_version("35.012.2011.19"))  # Leading 0
    self.assertFalse(versions.is_valid_version("35.K12.2011.19"))  # Non-digits
    self.assertFalse(versions.is_valid_version("35.2011.19"))  # 3 groups only


class IsValidRevisionTest(TestCase):

  def test_valid_revisions(self):
    self.assertTrue(versions.is_valid_revision(VALID_40D_REVISION_NO_A))
    self.assertTrue(versions.is_valid_revision(VALID_6D_REVISION_NO_A, 6))

  def test_invalid_revisions(self):
    self.assertFalse(versions.is_valid_revision(INVALID_REVISION_FORMAT_1))
    self.assertFalse(versions.is_valid_revision(INVALID_REVISION_FORMAT_2))
    self.assertFalse(versions.is_valid_revision(INVALID_REVISION_FORMAT_3))
    self.assertFalse(versions.is_valid_revision(VALID_40D_REVISION_NO_B, 6))


class LocalMemoryProviderTest(TestCase):

  def test_retrieve(self):
    provider = versions.LocalMemoryProvider()
    provider.version_by_revision = {
        VALID_40D_REVISION_NO_A: "94.0.4606.71",
        INVALID_REVISION_NO_1: None,
    }

    self.assertEqual(provider.retrieve(VALID_40D_REVISION_NO_A), "94.0.4606.71")

    D = versions.DOES_NOT_EXIST
    self.assertEqual(provider.retrieve(INVALID_REVISION_NO_1), D)

    C = versions.CONTINUE_SEARCH
    self.assertEqual(provider.retrieve(INVALID_REVISION_NO_2), C)

  def test_process_response(self):
    provider = versions.LocalMemoryProvider()

    # Version and None is CACHED if returned by ANOTHER provider
    provider.process_response(None, VALID_40D_REVISION_NO_A, "1.1.1.1")
    provider.process_response(None, VALID_40D_REVISION_NO_B, None)

    self.assertEqual(provider.retrieve(VALID_40D_REVISION_NO_A), "1.1.1.1")

    D = versions.DOES_NOT_EXIST
    self.assertEqual(provider.retrieve(VALID_40D_REVISION_NO_B), D)

    # Version is NOT CACHED if returned by the SAME provider
    provider = versions.LocalMemoryProvider()
    provider.process_response(provider, INVALID_REVISION_NO_1, "1.1.1.2")

    C = versions.CONTINUE_SEARCH
    self.assertEqual(provider.retrieve(INVALID_REVISION_NO_1), C)


class LocalBucketProviderTest(TestCase):

  def get_provider(self, initial_blobs=None):
    provider = versions.LocalBucketProvider()
    provider.bucket = MockedBucket(initial_blobs)
    return provider

  @mock.patch("versions.storage")
  def test_retrieve(self, *mocks):  # pylint: disable=W0613
    provider = self.get_provider({
        f"version_by_revision/{VALID_40D_REVISION_NO_A}":
            MockedBlob.from_content(b"94.0.4606.71"),
    })

    self.assertEqual(provider.retrieve(VALID_40D_REVISION_NO_A), "94.0.4606.71")

    C = versions.CONTINUE_SEARCH
    self.assertEqual(provider.retrieve(INVALID_REVISION_NO_1), C)

  @mock.patch("versions.storage")
  def test_process_response(self, *mocks):  # pylint: disable=W0613
    provider = self.get_provider()

    # Version is CACHED if returned by ANOTHER provider
    provider.process_response(None, VALID_40D_REVISION_NO_A, "1.1.1.1")
    self.assertEqual(provider.retrieve(VALID_40D_REVISION_NO_A), "1.1.1.1")

    # Response None is NOT CACHED
    C = versions.CONTINUE_SEARCH

    provider.process_response(None, INVALID_REVISION_NO_1, None)
    self.assertEqual(provider.retrieve(INVALID_REVISION_NO_1), C)

    # Version is NOT CACHED if returned by the SAME provider
    provider = versions.LocalMemoryProvider()
    provider.process_response(provider, INVALID_REVISION_NO_2, "1.1.1.2")
    self.assertEqual(provider.retrieve(INVALID_REVISION_NO_1), C)


def mocked_dash_get(url, timeout=10):  # pylint: disable=W0613
  base = "https://chromiumdash.appspot.com/fetch_commit?commit=%s"

  if url == base % VALID_40D_REVISION_NO_A:
    return MockedResponse('{"earliest": "94.0.4606.71"}', 200)

  if url == base % INVALID_REVISION_NO_1:
    return MockedResponse('{"error": "Commit not found."}', 200)

  if url == base % INVALID_REVISION_NO_2:
    return MockedResponse('{"error": "Invalid error"}', 200)

  if url == base % INVALID_REVISION_NO_3:
    return MockedResponse('{"earliest": "940460671"}', 200)

  if url == base % INVALID_REVISION_NO_4:
    return MockedResponse('{"earliest": null}', 200)

  raise NotImplementedError(f"Url {url} not mocked")


class ChromiumDashProviderTest(TestCase):

  @mock.patch("versions.requests.get", side_effect=mocked_dash_get)
  def test_retrieve(self, *mocks):  # pylint: disable=W0613
    provider = versions.ChromiumDashProvider()
    self.assertEqual(provider.retrieve(VALID_40D_REVISION_NO_A), "94.0.4606.71")

    C = versions.CONTINUE_SEARCH
    self.assertEqual(provider.retrieve(INVALID_REVISION_NO_1), C)
    self.assertEqual(provider.retrieve(INVALID_REVISION_NO_2), C)
    self.assertEqual(provider.retrieve(INVALID_REVISION_NO_3), C)
    self.assertEqual(provider.retrieve(INVALID_REVISION_NO_4), C)


def mocked_repository_get(url, timeout=10):  # pylint: disable=W0613
  base = ("https://chromium.googlesource.com/chromium/src/+/%s"
          "/chrome/VERSION?format=TEXT")

  if url == base % VALID_40D_REVISION_NO_A:
    return MockedResponse(
        base64.b64encode(b"MAJOR=94\nMINOR=0\nBUILD=4606\nPATCH=71\n"), 200)

  if url == base % INVALID_REVISION_NO_1:
    return MockedResponse(b"", 404)

  if url == base % INVALID_REVISION_NO_2:
    return MockedResponse(base64.b64encode(b"invalid-response"), 200)

  if url == base % INVALID_REVISION_NO_3:
    return MockedResponse(b"invalid-response", 200)

  if url == base % INVALID_REVISION_NO_4:
    raise requests.exceptions.ReadTimeout()

  raise NotImplementedError(f"Url {url} not mocked")


class ChromiumRepositoryProviderTest(TestCase):

  @mock.patch("versions.requests.get", side_effect=mocked_repository_get)
  def test_retrieve(self, *mocks):  # pylint: disable=W0613
    provider = versions.ChromiumRepositoryProvider()
    self.assertEqual(provider.retrieve(VALID_40D_REVISION_NO_A), "94.0.4606.71")

    D = versions.DOES_NOT_EXIST
    self.assertEqual(provider.retrieve(INVALID_REVISION_NO_1), D)

    C = versions.CONTINUE_SEARCH
    self.assertEqual(provider.retrieve(INVALID_REVISION_NO_2), C)
    self.assertEqual(provider.retrieve(INVALID_REVISION_NO_3), C)
    self.assertEqual(provider.retrieve(INVALID_REVISION_NO_4), C)


if __name__ == "__main__":
  sys.exit(pytest.main([__file__]))
