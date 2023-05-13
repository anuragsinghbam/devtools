#!/usr/bin/env python3
# Copyright (c) 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import sys

USE_PYTHON3 = True


def _RunYapf(input_api, output_api, yapf_only_changed=True):
  presubmit_base_path = input_api.PresubmitLocalPath()

  if input_api.is_committing:
    error_message = output_api.PresubmitError
  else:
    error_message = output_api.PresubmitPromptWarning

  cmd = ['yapf', '--diff']
  if yapf_only_changed:
    changed_files = input_api.change.AbsoluteLocalPaths()
    changed_py_files = filter(lambda f: f.endswith('.py'), changed_files)
    cmd += [
        input_api.os_path.relpath(cf, presubmit_base_path)
        for cf in changed_py_files
    ]
  else:
    cmd += ['--recursive', presubmit_base_path]

  return input_api.RunTests([
      input_api.Command(
          name='Running YAPF; call `yapf -irp .` to fix formatting issues',
          cmd=cmd,
          message=error_message,
          kwargs={},
          python3=True,
      )
  ])


def CommonChecks(input_api, output_api, yapf_only_changed=True):
  results = []

  # Run YAPF
  results.extend(_RunYapf(input_api, output_api, yapf_only_changed))

  return results

  # Run Python unittests.
  results.extend(
      input_api.canned_checks.RunUnitTestsInDirectory(
          input_api, output_api, '.', [r'^.+_test\.py$'], run_on_python2=False))

  # Check for license header
  results.extend(input_api.canned_checks.CheckLicense(input_api, output_api))

  return results


def CheckChangeOnUpload(input_api, output_api):
  return CommonChecks(input_api, output_api, yapf_only_changed=True)


def CheckChangeOnCommit(input_api, output_api):
  return CommonChecks(input_api, output_api, yapf_only_changed=False)
