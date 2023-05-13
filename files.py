#!/usr/bin/env python3
# Copyright (c) 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from abc import ABC, abstractmethod
from distutils.version import LooseVersion
import io
import logging
import re
from typing import cast, List, Optional, Set, Tuple
import zipfile

from config import CHROME_UNSIGNED_ARTIFACT_PATH
from config import CHROME_UNSIGNED_BUCKET
from config import CHROME_UNSIGNED_DT_FRONTEND_ZIP_BASE_DIRS
from config import CHROME_UNSIGNED_DT_INTERNAL_ZIP_BASE_DIRS
from config import LEGACY_BUCKET
from config import LOCAL_BUCKET
from config import Project
from google.cloud import storage
from pipelines import BaseProvider
from pipelines import CONTINUE_SEARCH
from pipelines import DOES_NOT_EXIST
from pipelines import Pipeline
from storage_helper import download_blob
from storage_helper import upload_from_string
from versions import get_version_from_revision
from versions import is_valid_revision
from versions import is_valid_version

LAST_LEGACY_MAJOR = 99


class BaseFileProvider(BaseProvider[Tuple[str, str], bytes], ABC):
  """File providers expect a str tuple (revision, filename), and return a bytes
  content (the file)."""

  @abstractmethod
  def get_bucketname(self):
    pass

  def __init__(self):
    self.bucket = storage.Client().bucket(self.get_bucketname())


class LocalBucketProvider(BaseFileProvider):
  """Retrieve and store files from and to a local (cache) bucket."""

  def __init__(self, storage_suffix: Optional[str] = None):
    self.storage_suffix = storage_suffix
    return super().__init__()

  def get_bucketname(self):
    return LOCAL_BUCKET

  def get_local_path(self, revision, filename):
    """Return the storage path for a given file within the local bucket."""

    # The initial version was only serving devtools-frontend files which are
    # stored without a suffix. All files will be stored under the proejct suffix
    if self.storage_suffix is None:
      return f"extracted/{revision}/{filename}"

    return f"extracted/{revision}-{self.storage_suffix}/{filename}"

  def retrieve(self, params):
    # Retrieve blob content from local bucket
    path = self.get_local_path(*params)
    blob = download_blob(self.bucket, path)

    if blob is None:
      return CONTINUE_SEARCH

    return blob

  def process_response(self, provider, params, content):
    # Save file content on local bucket
    if provider == self:
      return

    if content is None:
      return

    path = self.get_local_path(*params)
    blob = self.bucket.blob(path)
    upload_from_string(blob, content)


class ZipFileProvider(BaseFileProvider, ABC):
  ZIP_TOC_PATH = "tocs/%s/%s"

  def __init__(self):
    super().__init__()
    self.local_bucket = storage.Client().bucket(LOCAL_BUCKET)

  @abstractmethod
  def get_blobnames(self, revision, version):
    pass

  @abstractmethod
  def get_zip_base_dirs(self):
    pass

  def applies_to_version(self, major_version):  # pylint: disable=W0613
    return True

  def get_zip_toc_path(self, blobname):
    bucketname = self.get_bucketname()
    return self.ZIP_TOC_PATH % (bucketname, blobname)

  def is_any_file_in_zip(self, blobname,
                         filenames) -> Tuple[bool, Optional[str]]:
    """Validate that any of the files is listed in the zip's table of content.

    Args:
      blobname (str): Name of the zip archive
      filenames (str[]): One of the expected files within the zip

    Returns:
      Tuple[bool, Optional[str]]: (table of content exists, existing file)
    """
    toc_path = self.get_zip_toc_path(blobname)
    toc_blob = download_blob(self.local_bucket, toc_path)
    if toc_blob is None:
      logging.info("Requested zip toc for %s, but toc does not exist.",
                   toc_path)
      return False, None

    toc_file = toc_blob.decode("utf-8").strip('\n')

    for filename in filenames:
      if filename in toc_file.split("\n"):
        return True, filename

    return True, None

  def save_zip_toc(self, blobname, zip_file) -> Set[str]:
    files = filter(lambda zi: not zi.is_dir(), zip_file.infolist())
    toc = ""
    paths = set()
    for f in files:
      toc += f"{f.orig_filename}\n"
      paths.add(f.orig_filename)

    path = self.get_zip_toc_path(blobname)
    blob = self.local_bucket.blob(path)
    upload_from_string(blob, toc)

    return paths

  def extract_from_zip_blob(self, blobnames, filename):
    """Extract a file from a list of blobs.

    Searches for the first existing blob in a list of blobs and extracts the
    file.

    Args:
      blobnames (str[]): List of potentially existing blobs
      filename (str): File to extract from the blob

    Returns:
      Union[bytes, DOES_NOT_EXIST, CONTINUE_SEARCH]
    """
    paths = [f"{path}{filename}" for path in self.get_zip_base_dirs()]

    for blobname in blobnames:
      # Validate that file is in zip's table of content
      toc_exists, path = self.is_any_file_in_zip(blobname, paths)
      if toc_exists and path is None:
        logging.info(
            "None of the requested files %s found in toc of archive %s.",
            ", ".join(paths),
            blobname,
        )
        return DOES_NOT_EXIST

      # Retrieve zip archive
      content = download_blob(self.bucket, blobname)
      if content is None:
        logging.warning("Requested file %s, but the archive %s does not exist",
                        filename, blobname)
        continue

      # Extract requested file
      with io.BytesIO(content) as zip_bytes, \
          zipfile.ZipFile(zip_bytes) as zip_file:

        if not toc_exists:
          paths_in_zip = self.save_zip_toc(blobname, zip_file)

          for p in paths:
            if p in paths_in_zip:
              path = p
              break

          if path is None:
            logging.info("File %s not found in gs://%s/%s", filename,
                         self.get_bucketname(), blobname)
            return DOES_NOT_EXIST

        return zip_file.read(path)

    return CONTINUE_SEARCH

  def retrieve(self, params):
    revision, name = params

    version = get_version_from_revision(revision)
    if version is None:
      logging.info("Skip provider; no version found for revision %s", revision)
      return CONTINUE_SEARCH

    major = int(version.split(".")[0])
    if not self.applies_to_version(major):
      logging.info("Skip provider; major version %s not applicable", major)
      return CONTINUE_SEARCH

    blobnames = self.get_blobnames(revision, version)
    if len(blobnames) == 0:
      logging.info("Skip provider; no zip-archive found for revision %s",
                   revision)
      return CONTINUE_SEARCH

    return self.extract_from_zip_blob(blobnames, name)


class ChromeUnsignedProvider(ZipFileProvider):
  """Retrieve devtools-frontend.zip artifacts from chrome's signed binary
  bucket.

  Artifacts are available from chrome's signed bucket for M100 and
  later.
  """

  def __init__(self, base_dirs: List[str]):
    self.base_dirs = base_dirs
    return super().__init__()

  def get_bucketname(self):
    return CHROME_UNSIGNED_BUCKET

  def get_zip_base_dirs(self):
    return self.base_dirs

  def applies_to_version(self, major_version):
    return major_version > LAST_LEGACY_MAJOR

  def get_blobnames(self, revision, version):  # pylint: disable=W0613
    if version is None:
      return []

    # Generate a list of patch versions down to 0, e.g. 100.0.5911.3 returns
    # ["100.0.5911.3", "100.0.5911.2", "100.0.5911.1", "100.0.5911.0"]
    v = LooseVersion(version)
    patch_versions = [
        ".".join(version.split(".")[:3] + [str(patch)])
        for patch in reversed(range(0, v.version[3] + 1))
    ]

    return [
        CHROME_UNSIGNED_ARTIFACT_PATH % patch_version
        for patch_version in patch_versions
    ]


class LegacyBucketMixin:

  def get_bucketname(self):
    return LEGACY_BUCKET


class LegacyM99ZipProvider(LegacyBucketMixin, ZipFileProvider, ABC):
  """Retrieve devtools-frontend.zip artifacts from the legacy bucket.

  Artifacts have been uploaded to the local bucket till M99.
  """

  LEGACY_M99_REVS_PATH = "revs/@%s"
  LEGACY_M99_ZIPS_PATH = "zips/%s.zip"

  def get_zip_base_dirs(self):
    return ['']

  def get_meta_filename(self, revision, version):  # pylint: disable=W0613
    return self.LEGACY_M99_REVS_PATH % revision

  def get_blobnames(self, revision, version):
    meta_filename = self.get_meta_filename(revision, version)
    meta_blob = download_blob(self.bucket, meta_filename)
    if meta_blob is None:
      logging.warning("Requested file %s does not exist", meta_filename)
      return []

    zip_file_name = meta_blob.decode("utf-8").strip(' \t\n')

    return [self.LEGACY_M99_ZIPS_PATH % zip_file_name]


class LegacyM99LongRevisionProvider(LegacyM99ZipProvider):
  """Retrieve devtools-frontend.zip artifacts for 40-digit revisions."""

  def applies_to_version(self, major_version):
    return major_version <= LAST_LEGACY_MAJOR


class LegacyM99ShortRevisionProvider(LegacyM99ZipProvider):
  """Retrieve devtools-frontend.zip artifacts for 6-digit revisions.

  Initial chrome revisions have been identified by using the first 6
  digits only. This provider serves artifacts for those revisions.

  6-digit revisions are ambiguous within the Chromium project, and a mapping to
  a specific version is not possible. Chromium uses 40-digit revisions more
  recently. This provider assumes that all requested 6-digit versions origin
  from pre-M100 versions and searches for corresponding files on the legacy
  bucket.

  The version check is skipped for these short revisions.
  """

  def retrieve(self, params):
    revision, name = params

    if not is_valid_revision(revision, 6):
      logging.info("Skip %s; revision %s not applicable", self.name, revision)
      return CONTINUE_SEARCH

    blobnames = self.get_blobnames(revision, None)
    if len(blobnames) == 0:
      logging.info("Skip %s; no zip-archive found for revision %s", self.name,
                   revision)
      return CONTINUE_SEARCH

    return self.extract_from_zip_blob(blobnames, name)


class LegacyM99StaticVersionProvider(LegacyM99ZipProvider):
  """Retrieve devtools-frontend.zip artifacts for legacy versions."""

  LEGACY_M99_VERS_PATH = "vers/%s"

  def get_meta_filename(self, revision, version):  # pylint: disable=W0613
    return self.LEGACY_M99_VERS_PATH % version

  def retrieve(self, params):
    version, name = params

    if not is_valid_version(version):
      logging.warning("Skip %s; invalid version %s provided", self.name,
                      version)
      return CONTINUE_SEARCH

    # Artifacts are not available for patch versions, so we replace the patch
    # number with 0
    version = re.sub(r"\.\d+$", ".0", version)

    blobnames = self.get_blobnames(None, version)
    if len(blobnames) == 0:
      logging.info("Skip %s; no zip-archive found for version %s", self.name,
                   version)
      return CONTINUE_SEARCH

    return self.extract_from_zip_blob(blobnames, name)


class LegacyM99FilesProvider(LegacyBucketMixin, BaseFileProvider):
  """Retrieve an already extracted file stored at the local bucket.

  This provider returns the same files as the legacy
  /serve_file/<revision>/<filename> endpoint.

  Some of the revisions served via this endpoint are not part of the Chromium
  repository. We skip a check for a pre-M100 version.

  The legacy bucket has the following structure. For a request (e.g. GET
  /serve_file/@e2206c2e9067be8fc1dea2050e67246228949ff/demo.js), the provider

  1) searches for the file hash of demo.js in gs://legacy-bucket/meta/@e2206c…
  ```
  …
        911feebcaa974b936128173b5ec89115d354223f:logo.ico
        220bcaa974b936128173b5ec89115d354223f8ab:demo.js   ◄
        f8ab220bcaa974b936128173b5ec89115d354223:bg.jpg
  …
        ```

        2) Serves the file in gs://legacy-bucket/hash/220bca…
  """

  LEGACY_M99_META_PATH = "meta/@%s"
  LEGACY_M99_HASH_PATH = "hash/%s"

  def retrieve(self, params):
    revision, name = params

    # Load ToC including hashes for this revision
    meta_filename = self.LEGACY_M99_META_PATH % revision
    meta_blob = download_blob(self.bucket, meta_filename)
    if meta_blob is None:
      logging.info("Skip provider; meta file %s does not exist", meta_filename)
      return CONTINUE_SEARCH

    # Find requested file hash and name in ToC
    hash_entries = (meta_blob.decode("utf-8").strip("\n").split('\n'))
    file_hash = None

    for hash_entry in hash_entries:
      current_file_hash, current_filename = hash_entry.split(":", maxsplit=1)
      if current_filename == name:
        file_hash = current_file_hash
        break

    if file_hash is None:
      logging.info("Skip provider; file %s does not exist in %s", name,
                   meta_filename)
      return CONTINUE_SEARCH

    # Download file from hash folder
    hash_filename = self.LEGACY_M99_HASH_PATH % file_hash
    hash_blob = download_blob(self.bucket, hash_filename)
    if hash_blob is None:
      logging.warning(
          "Skip provider; hash file %s does not exist for revision %s",
          hash_filename, revision)
      return CONTINUE_SEARCH

    return hash_blob


# The order is important since the next provider will only be requested if the
# current provider cannot find a matching file. Providers at the top are less
# complete but have a lower latency. We use a lazy init approach to avoid call-
# outs when starting the app.

_PIPELINES = {}


def get_revision_pipeline(project: Project) -> Pipeline[Tuple[str, str], bytes]:
  global _PIPELINES
  singleton_key = f"revision__{project.value}"

  if singleton_key in _PIPELINES:
    return _PIPELINES[singleton_key]

  if project == Project.DEVTOOLS_FRONTEND:
    pipeline = Pipeline[Tuple[str, str], bytes]([
        LocalBucketProvider(),
        ChromeUnsignedProvider(CHROME_UNSIGNED_DT_FRONTEND_ZIP_BASE_DIRS),
        LegacyM99LongRevisionProvider(),
        LegacyM99ShortRevisionProvider(),
        LegacyM99FilesProvider(),
    ])

  if project == Project.DEVTOOLS_INTERNAL:
    pipeline = Pipeline[Tuple[str, str], bytes]([
        LocalBucketProvider(project.value),
        ChromeUnsignedProvider(CHROME_UNSIGNED_DT_INTERNAL_ZIP_BASE_DIRS),
    ])

  _PIPELINES[singleton_key] = pipeline

  return _PIPELINES[singleton_key]


def get_version_pipeline() -> Pipeline[Tuple[str, str], bytes]:
  global _PIPELINES
  return _PIPELINES.setdefault(
      'version', Pipeline[Tuple[str, str], bytes]([
          LegacyM99StaticVersionProvider(),
      ]))


def get_file_from_revision(revision: str, filename: str,
                           project: Project) -> Optional[bytes]:
  """Return the content of a file from a revision.

  Args:
    revision (str): Chrome revision
    filename (str): filepath without starting slash /
    project (Project): Project to serve file from

  Returns:
    Optional[bytes]: File content or None if no file was retrieved
  """
  params = revision, filename
  return get_revision_pipeline(project).retrieve(params)


def get_file_from_version(version: str, filename: str) -> Optional[bytes]:
  """Return the content of a file from a version.

  Args:
    version (str): Chrome version <major.minor.build.patch>
    filename (str): filepath without starting slash /

  Returns:
    Optional[bytes]: File content or None if no file was retrieved
  """
  params = version, filename
  return get_version_pipeline().retrieve(params)
