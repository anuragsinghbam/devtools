#!/usr/bin/env python3
# Copyright (c) 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.
"""A webserver for devtools frontend assets."""

import gzip
import mimetypes

from config import MAX_CACHE_AGE
from files import get_file_from_revision
from files import get_file_from_version
from files import Project
import flask
from logger import usage_logger
import markdown
import startup_checks
from versions import get_version_from_revision


# Custom flask server to execute startup checks before serving files
class StartupCheckFlask(flask.Flask):

  def run(self, *args, **kwargs):
    startup_checks.run()
    return super().run(*args, **kwargs)


def create_file_response(filename: str, content: bytes) -> flask.Response:
  # Content Type
  content_type = mimetypes.guess_type(filename)[0] or "text/plain"

  # Generate response
  response = flask.Response(content)
  response.headers["Content-Type"] = content_type
  response.headers["Cache-Control"] = f"public, max-age={MAX_CACHE_AGE}"
  response.headers['Access-Control-Allow-Origin'] = '*'

  # Gzip the response if supported by the client
  encodings = flask.request.headers.get("accept-encoding")
  if encodings and "gzip" in encodings.replace(" ", "").split(","):
    new_data = gzip.compress(response.data)
    response.set_data(new_data)
    response.headers["Content-Encoding"] = "gzip"

  return response


# If `entrypoint` is not defined in app.yaml, App Engine will look for an app
# called `app` in `main.py`.
app = StartupCheckFlask(__name__)


@app.route("/")
def index():
  with open("templates/markdown.html") as pre_content_file, \
      open("README.md") as readme_file:

    style_html = pre_content_file.read()
    content_html = markdown.markdown(readme_file.read())
    return style_html + content_html


@app.route("/serve_rev/@<string:revision>/<path:filename>")
def serve_rev(revision: str,
              filename: str,
              project: Project = Project.DEVTOOLS_FRONTEND) -> flask.Response:
  """Return the devtools file for a given revision and project.

  1. Convert the revision (=commit hash) to the first Chromium version which
     includes this commit.

  2. Retrieve the requested filename for this version.

  Returns:
    200: Existing revision, remote archive and file.
    404: Invalid or non-existing revisions.
    404: Non-existing files within the zip-archive.
    500: Unhandled code exceptions.
  """
  # Log revision and version mapping
  usage_logger.log_struct({
      "type": "version",
      "body": {
          "revision": revision,
          "version": get_version_from_revision(revision),
          "source": "serve_rev"
      }
  })

  # Retrieve file for revision
  content = get_file_from_revision(revision, filename, project)
  if content is None:
    return flask.abort(404)

  return create_file_response(filename, content)


@app.route("/serve_file/@<string:revision>/<path:filename>")
def serve_file(revision: str, filename: str) -> flask.Response:
  # We keep this endpoint for legacy reasons
  return serve_rev(revision, filename, Project.DEVTOOLS_FRONTEND)


@app.route("/serve_internal_file/@<string:revision>/<path:filename>")
def serve_internal_file(revision: str, filename: str) -> flask.Response:
  return serve_rev(revision, filename, Project.DEVTOOLS_INTERNAL)


@app.route("/static/<string:version>/<path:filename>")
def serve_static(version: str, filename: str) -> flask.Response:
  """Return the devtools frontend file for a given version from the legacy
  bucket.

  Returns:
    200: Existing revision, remote archive and file.
    404: Invalid or non-existing revisions.
    404: Non-existing files within the zip-archive.
    500: Unhandled code exceptions.
  """
  # Log revision and version mapping
  usage_logger.log_struct({
      "type": "version",
      "body": {
          "revision": None,
          "version": version,
          "source": "serve_static"
      }
  })

  # Retrieve file for revision
  content = get_file_from_version(version, filename)
  if content is None:
    return flask.abort(404)

  return create_file_response(filename, content)


if __name__ == "__main__":
  # This is used when running locally only. When deploying to Google App
  # Engine, a webserver process such as Gunicorn will serve the app. You
  # can configure startup instructions by adding `entrypoint` to app.yaml.
  app.run(host="0.0.0.0", port=8080, debug=True)
