#!/usr/bin/env python3
# Copyright (c) 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import sys
from unittest import mock
from unittest import TestCase

from pipelines import BaseProvider
from pipelines import CONTINUE_SEARCH
from pipelines import Pipeline
import pytest

VALID_PARAM_1 = "param-1"
VALID_PARAM_2 = "param-2"
INVALID_PARAM_A = "invalid-param-A"
INVALID_PARAM_B = "invalid-param-B"

RESPONSE_1 = "response-1"
RESPONSE_2 = "response-1"


class FirstProvider(BaseProvider[str, str]):

  def __init__(self):
    self.cache = {}

  def retrieve(self, param):
    if param == VALID_PARAM_1:
      return RESPONSE_1
    return CONTINUE_SEARCH

  def process_response(self, provider, param, content):
    self.cache[param] = (provider, content)

  def clear_cache(self):
    self.cache = {}


class SecondProvider(BaseProvider[str, str]):

  def retrieve(self, param):
    if param == VALID_PARAM_2:
      return RESPONSE_2
    return CONTINUE_SEARCH


class PipelineTest(TestCase):

  def get_mocked_providers(self):
    return [FirstProvider(), SecondProvider()]

  def test_provider_pipeline(self):
    fp, sp = self.get_mocked_providers()

    pl = Pipeline[str, str]([fp, sp])

    # Request some content from the pipeline
    self.assertEqual(pl.retrieve(VALID_PARAM_1), RESPONSE_1)
    self.assertEqual(pl.retrieve(VALID_PARAM_2), RESPONSE_2)
    self.assertIsNone(pl.retrieve(INVALID_PARAM_A))

    # Validate content was added to the cache
    self.assertEqual(fp.cache[VALID_PARAM_1], (fp, RESPONSE_1))
    self.assertEqual(fp.cache[VALID_PARAM_2], (sp, RESPONSE_2))
    self.assertEqual(fp.cache[INVALID_PARAM_A], (None, None))
    self.assertNotIn(INVALID_PARAM_B, fp.cache)


if __name__ == "__main__":
  sys.exit(pytest.main([__file__]))
