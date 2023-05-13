#!/usr/bin/env python3
# Copyright (c) 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import io
import sys
from unittest import mock
from unittest import TestCase
import zipfile

from config import CHROME_UNSIGNED_ARTIFACT_PATH
from config import CHROME_UNSIGNED_DT_FRONTEND_ZIP_BASE_DIRS
from config import Project
import files
from mocks.google_cloud_storage import MockedBlob
from mocks.google_cloud_storage import MockedBucket
import pytest

C = files.CONTINUE_SEARCH
D = files.DOES_NOT_EXIST

VERSION_1 = "1.1.1.1"
VERSION_1_PATCH_0 = "1.1.1.0"
VERSION_2 = "2.1.9.1"
VERSION_100 = "100.1.5678.1"
INVALID_VERSION = "100.1.5678"

REVISION_1 = "1b8b78f5838ed0b1c69bb4e51ea0252171854915"
REVISION_2 = "ab8b78f5838ed0b1c69bb4e51ea0252171854915"
REVISION_6D = "bbb878"
REVISION_100 = "2b8b78f5838ed0b1c69bb4e51ea0252171854915"

VALID_FILE_A = "valid-A"
VALID_FILE_B = "valid-B"
VALID_FILE_C = "valid-C"
INVALID_FILE_1 = "invalid-1"
INVALID_FILE_2 = "invalid-2"

PROJECT_FE = Project.DEVTOOLS_FRONTEND
PROJECT_IN = Project.DEVTOOLS_INTERNAL

DEMO_ZIP_NAME = "2b8b78f5838ed0b1c69bb4e51ea025217185491a"
SAMPLE_CONTENT_1 = b"sample-content-1"
SAMPLE_CONTENT_2 = b"sample-content-2"


def get_version_from_revision(revision):
  if revision == REVISION_1:
    return VERSION_1

  if revision == REVISION_2:
    return VERSION_2

  if revision == REVISION_100:
    return VERSION_100

  return None


def extract_from_zip_blob(blobnames, filename):  # pylint: disable=W0613
  return SAMPLE_CONTENT_1


class LocalBucketProviderTest(TestCase):

  def get_provider(self, storage_suffix):
    provider = files.LocalBucketProvider(storage_suffix)
    provider.bucket = MockedBucket({
        f"extracted/{REVISION_1}/{VALID_FILE_A}":
            MockedBlob.from_content(SAMPLE_CONTENT_1),
        f"extracted/{REVISION_1}-{PROJECT_IN.value}/{VALID_FILE_A}":
            MockedBlob.from_content(SAMPLE_CONTENT_2),
    })
    return provider

  @mock.patch("files.storage")
  def test_retrieve_project_file(self, *mocks):  # pylint: disable=W0613
    provider = self.get_provider(None)
    self.assertEqual(
        provider.retrieve((REVISION_1, VALID_FILE_A)), SAMPLE_CONTENT_1)

    provider = self.get_provider(PROJECT_IN.value)
    self.assertEqual(
        provider.retrieve((REVISION_1, VALID_FILE_A)), SAMPLE_CONTENT_2)

  @mock.patch("files.storage")
  def test_retrieve_invalid_file(self, *mocks):  # pylint: disable=W0613
    provider = self.get_provider(PROJECT_FE)
    self.assertEqual(provider.retrieve((REVISION_1, INVALID_FILE_1)), C)

  @mock.patch("files.storage")
  def test_process_response(self, *mocks):  # pylint: disable=W0613
    provider = self.get_provider(PROJECT_FE)

    # File is CACHED if returned by ANOTHER provider
    provider.process_response(None, (REVISION_1, VALID_FILE_B),
                              SAMPLE_CONTENT_1)
    self.assertEqual(
        provider.retrieve((REVISION_1, VALID_FILE_B)), SAMPLE_CONTENT_1)

    # Response None is NOT CACHED
    provider.process_response(None, (REVISION_1, VALID_FILE_C), None)
    self.assertEqual(provider.retrieve((REVISION_1, VALID_FILE_C)), C)


class MockZipFileProvider(files.ZipFileProvider):
  TEST_ZIP_PATH = 'test-path/'

  def __init__(self):
    self.get_blobnames_calls = 0
    self.applies_to_version_calls = 0
    super().__init__()

  def get_bucketname(self):
    return 'mock-bucketname'

  def get_blobnames(self, revision, version):  # pylint: disable=W0613
    self.get_blobnames_calls += 1
    if version == VERSION_1:
      return [version]
    return []

  def get_zip_base_dirs(self):
    return [self.TEST_ZIP_PATH]

  def applies_to_version(self, major_version):
    self.applies_to_version_calls += 1
    return major_version < 5


class ZipFileProviderTest(TestCase):

  FILE_VALID = f"{MockZipFileProvider.TEST_ZIP_PATH}{VALID_FILE_A}"
  FILE_INVALID = f"{MockZipFileProvider.TEST_ZIP_PATH}{INVALID_FILE_1}"

  def get_provider(self):
    provider = MockZipFileProvider()

    # Add mock bucket with temporary zip file
    buffer_1 = io.BytesIO()
    with zipfile.ZipFile(buffer_1, "a") as zip_file:
      filename = f"{MockZipFileProvider.TEST_ZIP_PATH}{VALID_FILE_A}"
      zip_file.writestr(filename, SAMPLE_CONTENT_1)

    buffer_2 = io.BytesIO()
    with zipfile.ZipFile(buffer_2, "a") as zip_file:
      filename = f"{MockZipFileProvider.TEST_ZIP_PATH}{VALID_FILE_B}"
      zip_file.writestr(filename, SAMPLE_CONTENT_1)

    provider.bucket = MockedBucket({
        VERSION_1: MockedBlob.from_content(buffer_1.getvalue()),
        VERSION_2: MockedBlob.from_content(buffer_2.getvalue()),
    })

    provider.local_bucket = MockedBucket()

    return provider

  @mock.patch("files.storage")
  def test_is_any_file_in_zip(self, *mocks):  # pylint: disable=W0613
    provider = self.get_provider()

    # Add mock zip table of content for local bucket
    zip_toc_path = provider.get_zip_toc_path(VERSION_1)
    provider.local_bucket = MockedBucket({
        zip_toc_path:
            MockedBlob.from_content(f"{self.FILE_VALID}\n".encode("utf-8")),
    })

    self.assertEqual(
        provider.is_any_file_in_zip(VERSION_1, [self.FILE_VALID]),
        (True, self.FILE_VALID))

    self.assertEqual(
        provider.is_any_file_in_zip(
            VERSION_1, [self.FILE_INVALID, self.FILE_VALID, self.FILE_INVALID]),
        (True, self.FILE_VALID))

    self.assertEqual(provider.is_any_file_in_zip(VERSION_1, []), (True, None))

    self.assertEqual(
        provider.is_any_file_in_zip(VERSION_1, [self.FILE_INVALID]),
        (True, None))

    self.assertFalse(
        provider.is_any_file_in_zip(VERSION_2, [self.FILE_VALID])[0])

  @mock.patch("files.storage")
  def test_extract_from_zip_blob(self, *mocks):  # pylint: disable=W0613
    provider = self.get_provider()

    # No ToC exists yet
    toc_path = provider.get_zip_toc_path(VERSION_1)
    self.assertNotIn(toc_path, provider.local_bucket.blobs)

    # Happy path without pre-check in ToC
    params = ([VERSION_1], VALID_FILE_A)
    self.assertEqual(provider.extract_from_zip_blob(*params), SAMPLE_CONTENT_1)

    # After requesting the blob once, the ToC exists
    self.assertIn(toc_path, provider.local_bucket.blobs)

    # …and contains the test file
    toc_blob = provider.local_bucket.blobs.get(toc_path)
    self.assertIn(
        self.FILE_VALID,
        toc_blob.download_as_bytes().decode("utf-8").strip('\n').split("\n"))

    download_count = toc_blob._download_as_bytes_count

    # Happy path with pre-check in ToC
    params = ([VERSION_1], VALID_FILE_A)
    self.assertEqual(provider.extract_from_zip_blob(*params), SAMPLE_CONTENT_1)
    self.assertEqual(toc_blob._download_as_bytes_count, download_count + 1)

    # Archive does not exist in bucket
    params = ([VERSION_100], VALID_FILE_A)
    self.assertEqual(provider.extract_from_zip_blob(*params), C)

    # Second archive exists in bucket
    params = ([VERSION_100, VERSION_1], VALID_FILE_A)
    self.assertEqual(provider.extract_from_zip_blob(*params), SAMPLE_CONTENT_1)

    # File does not exist in archive
    params = ([VERSION_1], INVALID_FILE_1)
    self.assertEqual(provider.extract_from_zip_blob(*params), D)

    # File exists in second archive only
    params = ([VERSION_2, VERSION_1], VALID_FILE_A)
    self.assertEqual(provider.extract_from_zip_blob(*params), D)

    # No blob provided
    params = ([], VALID_FILE_A)
    self.assertEqual(provider.extract_from_zip_blob(*params), C)

  @mock.patch("files.storage")
  def test_extract_from_zip_blob_toc_creation(self, *mocks):  # pylint: disable=W0613
    provider = self.get_provider()

    # Archive table of content does not exist
    zip_toc_path = provider.get_zip_toc_path(VERSION_1)
    blob = provider.local_bucket.blobs.get(zip_toc_path)
    self.assertIsNone(blob)

    provider.extract_from_zip_blob([VERSION_1], VALID_FILE_A)

    # Archive table of contents is created
    blob = provider.local_bucket.blobs.get(zip_toc_path)
    filename = f"{MockZipFileProvider.TEST_ZIP_PATH}{VALID_FILE_A}"
    expected = (filename + "\n").encode("utf-8")
    self.assertEqual(blob.download_as_bytes(), expected)

  @mock.patch("files.storage")
  @mock.patch(
      "files.get_version_from_revision", side_effect=get_version_from_revision)
  def test_retrieve_happy_path(self, *mocks):  # pylint: disable=W0613
    provider = self.get_provider()
    self.assertEqual(
        provider.retrieve((REVISION_1, VALID_FILE_A)), SAMPLE_CONTENT_1)

  @mock.patch("files.storage")
  @mock.patch(
      "files.get_version_from_revision", side_effect=get_version_from_revision)
  def test_retrieve_invalid_revision(self, *mocks):  # pylint: disable=W0613
    provider = self.get_provider()
    self.assertEqual(provider.retrieve(('invalid-revision', VALID_FILE_A)), C)

  @mock.patch("files.storage")
  @mock.patch(
      "files.get_version_from_revision", side_effect=get_version_from_revision)
  def test_retrieve_inactive_major(self, *mocks):  # pylint: disable=W0613
    provider = self.get_provider()
    self.assertEqual(provider.retrieve((REVISION_100, VALID_FILE_A)), C)
    self.assertEqual(provider.applies_to_version_calls, 1)

  @mock.patch("files.storage")
  @mock.patch(
      "files.get_version_from_revision", side_effect=get_version_from_revision)
  def test_retrieve_invalid_blob(self, *mocks):  # pylint: disable=W0613
    provider = self.get_provider()
    self.assertEqual(provider.retrieve((REVISION_2, VALID_FILE_A)), C)
    self.assertEqual(provider.get_blobnames_calls, 1)


class ChromeUnsignedProviderTest(TestCase):

  def test_get_blobnames(self):
    Provider = files.ChromeUnsignedProvider
    blobnames_0 = Provider.get_blobnames(None, None, "9.0.12.0")  # type: ignore
    self.assertEqual(len(blobnames_0), 1)
    self.assertEqual(blobnames_0[0], CHROME_UNSIGNED_ARTIFACT_PATH % "9.0.12.0")

    blobnames_3 = Provider.get_blobnames(None, None, "9.0.12.3")  # type: ignore
    self.assertEqual(len(blobnames_3), 4)
    self.assertEqual(blobnames_3[0], CHROME_UNSIGNED_ARTIFACT_PATH % "9.0.12.3")
    self.assertEqual(blobnames_3[1], CHROME_UNSIGNED_ARTIFACT_PATH % "9.0.12.2")
    self.assertEqual(blobnames_3[2], CHROME_UNSIGNED_ARTIFACT_PATH % "9.0.12.1")
    self.assertEqual(blobnames_3[3], CHROME_UNSIGNED_ARTIFACT_PATH % "9.0.12.0")

  @mock.patch("files.storage")
  def test_get_zip_base_dirs(self, *mocks):  # pylint: disable=W0613
    provider = files.ChromeUnsignedProvider(
        CHROME_UNSIGNED_DT_FRONTEND_ZIP_BASE_DIRS)

    self.assertEqual(provider.get_zip_base_dirs()[0],
                     CHROME_UNSIGNED_DT_FRONTEND_ZIP_BASE_DIRS[0])


class LegacyM99ZipProviderTest(TestCase):

  @mock.patch("files.storage")
  def test_get_blobnames(self, *mocks):  # pylint: disable=W0613
    # Generate provider
    provider = files.LegacyM99ZipProvider()
    provider.bucket = MockedBucket({
        provider.LEGACY_M99_REVS_PATH % REVISION_1:
            MockedBlob.from_content(f"{DEMO_ZIP_NAME} \t\n".encode("utf-8")),
    })

    # Happy path
    self.assertEqual(
        provider.get_blobnames(REVISION_1, VERSION_1)[0],
        provider.LEGACY_M99_ZIPS_PATH % DEMO_ZIP_NAME)

    # No meta content exists
    self.assertEqual(len(provider.get_blobnames(REVISION_100, VERSION_100)), 0)


class LegacyM99ShortRevisionProviderTest(TestCase):

  @mock.patch("files.storage")
  @mock.patch(
      "files.LegacyM99ShortRevisionProvider.extract_from_zip_blob",
      side_effect=extract_from_zip_blob)
  def test_retrieve(self, *mocks):  # pylint: disable=W0613
    # Generate provider
    provider = files.LegacyM99ShortRevisionProvider()
    provider.bucket = MockedBucket({
        provider.LEGACY_M99_REVS_PATH % REVISION_6D:
            MockedBlob.from_content(f"{DEMO_ZIP_NAME} \t\n".encode("utf-8")),
    })

    # Happy path
    self.assertEqual(
        provider.retrieve((REVISION_6D, VALID_FILE_A)), SAMPLE_CONTENT_1)

    # Invalid revision
    self.assertEqual(provider.retrieve((REVISION_1, VALID_FILE_A)), C)


class LegacyM99StaticVersionProviderTest(TestCase):

  @mock.patch("files.storage")
  @mock.patch(
      "files.LegacyM99StaticVersionProvider.extract_from_zip_blob",
      side_effect=extract_from_zip_blob)
  def test_retrieve(self, *mocks):  # pylint: disable=W0613
    # Generate provider
    provider = files.LegacyM99StaticVersionProvider()
    provider.bucket = MockedBucket({
        provider.LEGACY_M99_VERS_PATH % VERSION_1_PATCH_0:
            MockedBlob.from_content(f"{DEMO_ZIP_NAME} \t\n".encode("utf-8")),
    })

    # Happy path
    self.assertEqual(
        provider.retrieve((VERSION_1, VALID_FILE_A)), SAMPLE_CONTENT_1)

    # No zip vers file
    self.assertEqual(provider.retrieve((VERSION_2, VALID_FILE_A)), C)

    # Invalid version
    self.assertEqual(provider.retrieve((INVALID_VERSION, VALID_FILE_A)), C)


class LegacyM99FilesProviderTest(TestCase):
  VALID_SHA_HASH_A = "220bcaa974b936128173b5ec89115d354223f8ab"
  INVALID_SHA_HASH_1 = "91abcaa974b936128173b5ec89115d354223f6cc"

  def get_provider(self):
    provider = files.LegacyM99FilesProvider()

    meta_path = provider.LEGACY_M99_META_PATH % REVISION_1
    hashed_file_path = provider.LEGACY_M99_HASH_PATH % self.VALID_SHA_HASH_A

    provider.bucket = MockedBucket({
        meta_path:
            MockedBlob.from_content((
                f"{self.VALID_SHA_HASH_A}:{VALID_FILE_A}\n"
                f"{self.INVALID_SHA_HASH_1}:{INVALID_FILE_1}\n").encode("utf-8")
                                   ),
        hashed_file_path:
            MockedBlob.from_content(SAMPLE_CONTENT_1),
    })

    return provider

  @mock.patch("files.storage")
  def test_retrieve(self, *mocks):  # pylint: disable=W0613
    provider = self.get_provider()
    self.assertEqual(
        provider.retrieve((REVISION_1, VALID_FILE_A)), SAMPLE_CONTENT_1)

    # No ToC meta file
    self.assertEqual(provider.retrieve((REVISION_2, VALID_FILE_A)), C)

    # No entry in ToC file
    self.assertEqual(provider.retrieve((REVISION_1, INVALID_FILE_2)), C)

    # Hash in ToC does not exist
    self.assertEqual(provider.retrieve((REVISION_1, INVALID_FILE_1)), C)


class GetPipelineTest(TestCase):

  @mock.patch("files.storage")
  def test_get_revision_pipeline(self, *mocks):  # pylint: disable=W0613
    self.assertGreater(
        len(files.get_revision_pipeline(PROJECT_FE).providers), 0)
    self.assertGreater(
        len(files.get_revision_pipeline(PROJECT_IN).providers), 0)

  @mock.patch("files.storage")
  def test_get_version_pipeline(self, *mocks):  # pylint: disable=W0613
    self.assertGreater(len(files.get_version_pipeline().providers), 0)


if __name__ == "__main__":
  sys.exit(pytest.main([__file__]))
