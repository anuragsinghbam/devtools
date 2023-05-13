#!/usr/bin/env python3
# Copyright (c) 2022 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import json
import logging

from config import IS_GAE


class FallbackLogger():

  def log_struct(self, body, *args, **kwargs):  # pylint: disable=W0613
    logging.info(json.dumps(body))


# Setup cloud logging within GAE scope only
if IS_GAE:
  import google.cloud.logging

  logging_client = google.cloud.logging.Client()

  # Add python's default logging stream to gcloud's logging stream `python`
  logging_client.setup_logging()

  # Add usage logs to gcloud's logging stream `usage`
  usage_logger = logging_client.logger("usage")

else:
  usage_logger = FallbackLogger()
