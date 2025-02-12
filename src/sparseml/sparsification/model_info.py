# Copyright (c) 2021 - present / Neuralmagic, Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Base classes for describing models and layers in ML framework neural networks.
"""


import json
from abc import ABC, abstractmethod
from collections import OrderedDict
from copy import deepcopy
from typing import Any, Dict, List, Optional, Union

import numpy

from sparseml.utils import clean_path, create_parent_dirs


__all__ = [
    "LayerInfo",
    "Result",
    "ModelResult",
    "ModelInfo",
]


class LayerInfo(object):
    """
    Class for storing properties about a layer in a model

    :param name: unique name of the layer within its model
    :param op_type: type of layer, i.e. "conv", "linear"
    :param params: number of non-bias parameters in the layer. must be
        included for prunable layers
    :param bias_params: number of bias parameters in the layer
    :param prunable: True if the layers non-bias parameters can be pruned.
        Default is False
    :param flops: optional number of float operations within the layer
    :param execution_order: optional execution order of the layer within the
        model. Default is -1
    :param attributes: optional dictionary of string attribute names to their
        values
    """

    def __init__(
        self,
        name: str,
        op_type: str,
        params: Optional[int] = None,
        bias_params: Optional[int] = None,
        prunable: bool = False,
        flops: Optional[int] = None,
        execution_order: int = -1,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        if prunable and not params:
            raise ValueError(
                f"Prunable layers must have non 0 number of params given {params} "
                f"for layer {name} with prunable set to {prunable}"
            )

        self.name = name
        self.op_type = op_type
        self.params = params
        self.bias_params = bias_params
        self.prunable = prunable
        self.flops = flops
        self.execution_order = execution_order
        self.attributes = attributes or {}

    @classmethod
    def linear_layer(
        cls, name: str, in_channels: int, out_channels: int, bias: bool, **kwargs
    ) -> "LayerInfo":
        """
        creates a LayerInfo object for a fully connected linear layer

        :param name: unique name of the layer within its model
        :param in_channels: number of input channels
        :param out_channels: number of output channels
        :param bias: True if the linear layer has a bias add included, False otherwise
        :param kwargs: additional kwargs to be passed to the LayerInfo constructor
        :return:
        """
        attributes = {
            "in_channels": in_channels,
            "out_channels": out_channels,
        }
        attributes.update(kwargs.get("attributes", {}))
        kwargs["attributes"] = attributes

        return cls(
            name=name,
            op_type="linear",
            params=in_channels * out_channels,
            bias_params=out_channels if bias else None,
            prunable=True,
            **kwargs,  # TODO: add FLOPS calculation
        )

    @classmethod
    def conv_layer(
        cls,
        name: str,
        in_channels: int,
        out_channels: int,
        kernel_shape: List[int],
        bias: bool,
        groups: int = 1,
        stride: Union[int, List[int]] = 1,
        padding: List[int] = None,
        **kwargs,
    ) -> "LayerInfo":
        """
        creates a LayerInfo object for a fully connected convolutional layer

        :param name: unique name of the layer within its model
        :param in_channels: number of input channels
        :param out_channels: number of output channels
        :param kernel_shape: kernel shape of this layer, given as a list
        :param bias: True if the linear layer has a bias add included, False otherwise
        :param groups: number of groups that input and output channels are divided into.
            default is 1
        :param stride: stride for this convolution, can be int or tuple of ints. default
            is 1
        :param padding: padding applied to each spatial axis. defualt is [0, 0, 0, 0]
        :param kwargs: additional kwargs to be passed to the LayerInfo constructor
        :return:
        """
        attributes = {
            "in_channels": in_channels,
            "out_channels": out_channels,
            "kernel_shape": kernel_shape,
            "groups": groups,
            "stride": stride,
            "padding": padding if padding is not None else [0, 0, 0, 0],
        }
        attributes.update(kwargs.get("attributes", {}))
        kwargs["attributes"] = attributes

        return cls(
            name=name,
            op_type="conv",
            params=in_channels * out_channels * numpy.prod(kernel_shape) // groups,
            bias_params=out_channels if bias else None,
            prunable=True,
            **kwargs,  # TODO: add FLOPS calculation
        )

    @classmethod
    def from_dict(cls, dictionary: Dict[str, Any]):
        """
        :param dictionary: dict serialized by LyaerInfo.from_dict
        :return: LayerInfo object created from the given dict
        """
        dictionary = deepcopy(dictionary)
        return cls(**dictionary)

    def to_dict(self) -> Dict[str, Any]:
        """
        :return: dict representation of this LayerInfo parameters
        """
        props = {
            "name": self.name,
            "op_type": self.op_type,
            "prunable": self.prunable,
            "execution_order": self.execution_order,
            "attributes": self.attributes,
        }
        if self.params is not None:
            props["params"] = self.params
        if self.bias_params is not None:
            props["bias_params"] = self.bias_params
        if self.flops is not None:
            props["flops"] = self.flops
        return props


class Result(object):
    """
    Base class for storing the results of an analysis

    :param value: initial value of the result. Defaults to None
    :param attributes: dict of attributes of this result. Defaults to empty
    """

    def __init__(self, value: Any = None, attributes: Optional[Dict[str, Any]] = None):
        self.value = value
        self.attributes = attributes or {}

    @classmethod
    def from_dict(cls, dictionary: Dict[str, Any]):
        """
        :param dictionary: dict serialized by Result.from_dict
        :return: Result object created from the given dict
        """
        dictionary = deepcopy(dictionary)
        return cls(**dictionary)

    def to_dict(self) -> Dict[str, Any]:
        """
        :return: dict representation of this Result
        """
        return {"value": self.value, "attributes": self.attributes}


class ModelResult(Result):
    """
    Class for storing the results of an analysis for an entire model

    :param analysis_type: name of the type of analysis that was performed
    :param value: initial value of the result. Defaults to None
    :param layer_results: dict of layer results to initialize for this model.
        Defaults to empty dict
    :param attributes: dict of attributes of this result. Defaults to empty
    """

    def __init__(
        self,
        analysis_type: str,
        value: Any = None,
        layer_results: Dict[str, Result] = None,
        attributes: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(value=value, attributes=attributes)

        self.analysis_type = analysis_type
        self.layer_results = layer_results or {}

    @classmethod
    def from_dict(cls, dictionary: Dict[str, Any]):
        """
        :param dictionary: dict serialized by ModelResult.from_dict
        :return: ModelResult object created from the given dict
        """
        dictionary = deepcopy(dictionary)
        dictionary["layer_results"] = dictionary.get("layer_results", {})
        dictionary["layer_results"] = {
            layer_name: Result.from_dict(layer_result)
            for layer_name, layer_result in dictionary["layer_results"].items()
        }
        return cls(**dictionary)

    def to_dict(self) -> Dict[str, Any]:
        """
        :return: dict representation of this ModelResult
        """
        dictionary = super().to_dict()
        dictionary["analysis_type"] = self.analysis_type
        dictionary["layer_results"] = {
            layer_name: layer_result.to_dict()
            for layer_name, layer_result in self.layer_results.items()
        }

        return dictionary


class ModelInfo(ABC):
    """
    Base class for extracting and serializing model metadata, layers info, and
    analysis results

    :param model: framework specific model object to extract info for
    """

    def __init__(self, model: Any, metadata: Dict[str, Any]):
        self.metadata = metadata

        if _is_layer_info_dict(model):
            self._layer_info = model
        else:
            model = self._validate_model(model)
            self._layer_info = self.extract_layer_info(model)

        self._analysis_results = []  # type: List[ModelResult]

    @classmethod
    def from_dict(cls, dictionary: Dict[str, Any]):
        """
        :param dictionary: dict serialized by ModelInfo.from_dict
        :return: ModelInfo object created from the given dict
        """
        dictionary = deepcopy(dictionary)
        if "layer_info" not in dictionary:
            raise ValueError(
                "ModelInfo objects serialized as a dict must include a 'layer_info' key"
            )
        layer_info = {
            name: LayerInfo.from_dict(info)
            for name, info in dictionary["layer_info"].items()
        }

        model_info = cls(layer_info, metadata=dictionary.get("metadata", {}))

        results = dictionary.get("analysis_results", [])
        for result in results:
            model_result = ModelResult.from_dict(result)
            model_info.add_analysis_result(model_result)

        return model_info

    @staticmethod
    def load(file_path) -> "ModelInfo":
        """
        :param file_path: file path to JSON file to load ModelInfo object from
        :return: the loaded ModelInfo object
        """
        file_path = clean_path(file_path)
        with open(file_path, "r") as file:
            model_info_dict = json.load(file)
        return ModelInfo.from_dict(model_info_dict)

    @property
    def layer_info(self) -> "OrderedDict[str, LayerInfo]":
        """
        :return: dict of unique layer name to LayerInfo object of the given layer
        """
        return self._layer_info

    @property
    def analysis_results(self) -> List[ModelResult]:
        """
        :return: list of analysis results run on this model
        """
        return self._analysis_results

    @abstractmethod
    def extract_layer_info(self, model: Any) -> "OrderedDict[str, LayerInfo]":
        """
        Abstract method for extracting an ordered dictionary of layer name to
        completed LayerInfo object for the layer

        :param model: model to extract LayerInfo information of
        :return: ordered dictionary of layer name to LayerInfo object for the layer
        """
        raise NotImplementedError()

    def add_analysis_result(self, result: ModelResult):
        for layer_name in result.layer_results:
            assert layer_name in self._layer_info
        self._analysis_results.append(result)

    def get_results_by_type(self, analysis_type: str) -> List[ModelResult]:
        """
        :param analysis_type: type of analysis in ModelResult.analysis_type to
            filter by
        :return: list of analysis results of this model that match the given type
        """
        return [
            result
            for result in self._analysis_results
            if result.analysis_type == analysis_type
        ]

    def to_dict(self) -> Dict[str, Any]:
        """
        :return: dict representation of this ModelResult
        """
        layer_info = {name: info.to_dict() for name, info in self._layer_info.items()}
        analysis_results = [result.to_dict() for result in self._analysis_results]
        return {
            "metadata": self.metadata,
            "layer_info": layer_info,
            "analysis_results": analysis_results,
        }

    def save(self, file_path: str):
        """
        saves the dict representation of this ModelInfo object as a JSON file
        to the given file path
        :param file_path: file path to save to
        """
        create_parent_dirs(file_path)
        with open(file_path, "w") as file:
            json.dump(self.to_dict(), file)

    @staticmethod
    def _validate_model(model: Any) -> Any:
        # perform any validation, unwrapping, pre-processing of model
        return model


def _is_layer_info_dict(obj: Any) -> bool:
    return isinstance(obj, Dict) and all(
        isinstance(val, LayerInfo) for val in obj.values()
    )
