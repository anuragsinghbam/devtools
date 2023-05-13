#!/usr/bin/env python3
# Copyright (c) 2021 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

from abc import ABC
import logging
from typing import Generic, List, Optional, TypeVar, Union

ParameterType = TypeVar('ParameterType')
ContentType = TypeVar('ContentType')


class ContinueSearch:
  pass


class DoesNotExist:
  pass


CONTINUE_SEARCH = ContinueSearch()
DOES_NOT_EXIST = DoesNotExist()


class BaseProvider(ABC, Generic[ParameterType, ContentType]):

  @property
  def name(self):
    return self.__class__.__name__

  # NOTE: Instead of ContinueSearch and DoesNotExist, Literal[CONTINUE_SEARCH]
  # should be used instead. However, python's typing library does not support
  # sentinel values yet.
  def retrieve(
      self,
      params: ParameterType  # pylint: disable=W0613
  ) -> Union[ContentType, ContinueSearch, DoesNotExist]:
    """Return content retrieved by the subclassed provider implementation.

    Args:
      params: Pipeline-specific parameters being passed to the providers.

    Returns:
      content (ContentType): Pipeline-specific content as a result of the
                             specific provider implementation
      DOES_NOT_EXIST: The requested content does not exist for given parameters
      CONTINUE_SEARCH: The provider cannot determine content, but another
                       provider might have it
    """
    return CONTINUE_SEARCH

  def process_response(
      self, provider: Optional['BaseProvider[ParameterType, ContentType]'],
      params: ParameterType, content: Optional[ContentType]) -> None:
    """Process the response if this provider is e.g. caching results.

    Args:
      provider (BaseProvider): Provider of the content; None if no provider
                               determined content
      params (ParameterType): Parameters leading to the content
      content (ContentType): Content retrieved by the provider; None if no
                             provider determined content
    """


class Pipeline(Generic[ParameterType, ContentType]):

  def __init__(self, providers: List[BaseProvider[ParameterType, ContentType]]):
    """Create a new pipeline which searches for content (ContentType) from a
    list of providers. The parameter (ParameterType) are passed to the
    provider's retrieval method.

    Args:
      providers (List[BaseProvider[ParameterType, ContentType]]):
          Sorted provider list used to retrieve content
    """
    self.providers = providers

  def retrieve(self, params: ParameterType) -> Optional[ContentType]:
    """Retrieve content from a list of pipeline providers.

    Iterate over all providers until content is found by calling `retrieve`.

    Call `process_response` for all passed providers in reverse order to
    postprocess the response.

    Args:
      params (ParameterType):
          Parameters passed to the providers for content retrieval

    Returns:
      Optional[ContentType]: Content or None if no content was determined
    """
    if len(self.providers) == 0:
      return None

    for idx, active_provider in enumerate(self.providers):
      response = active_provider.retrieve(params)
      if response is not CONTINUE_SEARCH:
        break
    else:
      active_provider = None

    active_provider_label = 'NoProvider'
    if active_provider:
      active_provider_label = active_provider.name

    # Set the resulting content
    # NOTE: We use `isinstance ContinueSearch` instead of `is CONTINUE_SEARCH`
    # to hint the type checker that `response` will be of type C.
    if isinstance(response, ContinueSearch):
      content = None
      logging.info("No pipe found content")
    elif isinstance(response, DoesNotExist):
      content = None
      logging.info("%s returned DoesNotExist", active_provider_label)
    else:
      content = response
      logging.info("%s returned content (%s)", active_provider_label,
                   len(content))

    # Call `process_response` in reverse order
    for provider in self.providers[idx::-1]:  # pylint: disable=W0631
      provider.process_response(active_provider, params, content)

    return content
