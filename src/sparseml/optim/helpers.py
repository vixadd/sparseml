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
Helper functions for base Modifier and Manger utilities
"""


import logging
import re
from typing import Any, Dict, Tuple, Union

import yaml

from sparseml.utils import UnknownVariableException, restricted_eval
from sparsezoo import Zoo
from sparsezoo.objects import Recipe


__all__ = [
    "load_recipe_yaml_str",
    "load_recipe_yaml_str_no_classes",
    "rewrite_recipe_yaml_string_with_classes",
    "update_recipe_variables",
    "evaluate_recipe_yaml_str_equations",
]

_LOGGER = logging.getLogger(__name__)


def load_recipe_yaml_str(
    file_path: Union[str, Recipe],
    **variable_overrides,
) -> str:
    """
    Loads a YAML recipe file to a string or
    extracts recipe from YAML front matter in a sparsezoo markdown recipe card.
    Recipes can also be provided as SparseZoo model stubs or Recipe
    objects.

    YAML front matter: https://jekyllrb.com/docs/front-matter/

    :param file_path: file path to recipe YAML file or markdown recipe card or
        stub to a SparseZoo model whose recipe will be downloaded and loaded.
        SparseZoo stubs should be preceded by 'zoo:', and can contain an optional
        '?recipe_type=<type>' parameter or include a `/<type>` subpath. Can also
        be a SparseZoo Recipe object. i.e. '/path/to/local/recipe.yaml',
        'zoo:model/stub/path', 'zoo:model/stub/path?recipe_type=transfer_learn',
        'zoo:model/stub/path/transfer_learn'
    :param variable_overrides: dict of variable values to replace
        in the loaded yaml string. Default is None
    :return: the recipe YAML configuration loaded as a string
    """
    if isinstance(file_path, Recipe):
        # download and unwrap Recipe object
        file_path = file_path.downloaded_path()

    if not isinstance(file_path, str):
        raise ValueError(f"file_path must be a str, given {type(file_path)}")

    if file_path.startswith("zoo:"):
        # download from zoo stub
        recipe = Zoo.download_recipe_from_stub(file_path)
        file_path = recipe.downloaded_path()

    # load the yaml string
    if "\n" in file_path or "\r" in file_path:
        # treat as raw yaml passed in
        yaml_str = file_path
        extension = "unknown"
    else:
        # load yaml from file_path
        extension = file_path.lower().split(".")[-1]
        if extension not in ["md", "yaml"]:
            raise ValueError(
                "Unsupported file extension for recipe. Excepted '.md' or '.yaml'. "
                f"Received {file_path}"
            )
        with open(file_path, "r") as yaml_file:
            yaml_str = yaml_file.read()

    if extension == "md" or extension == "unknown":
        # extract YAML front matter from markdown recipe card
        # adapted from
        # https://github.com/jonbeebe/frontmatter/blob/master/frontmatter
        yaml_delim = r"(?:---|\+\+\+)"
        yaml = r"(.*?)"
        re_pattern = r"^\s*" + yaml_delim + yaml + yaml_delim
        regex = re.compile(re_pattern, re.S | re.M)
        result = regex.search(yaml_str)

        if result:
            yaml_str = result.group(1)
        elif extension == "md":
            # fail if we know whe should have extracted front matter out
            raise RuntimeError(
                "Could not extract YAML front matter from recipe card:"
                " {}".format(file_path)
            )

    if variable_overrides:
        update_recipe_variables(yaml_str, variable_overrides)

    return yaml_str


def load_recipe_yaml_str_no_classes(recipe_yaml_str: str) -> str:
    """
    :param recipe_yaml_str: YAML string of a SparseML recipe
    :return: recipe loaded into YAML with all objects replaced
        as a dictionary of their parameters
    """
    pattern = re.compile(r"!(?P<class_name>(?!.*\.)[a-zA-Z_][a-zA-Z^._0-9]+)")
    classless_yaml_str = pattern.sub(r"OBJECT.\g<class_name>:", recipe_yaml_str)
    return yaml.safe_load(classless_yaml_str)


def rewrite_recipe_yaml_string_with_classes(recipe_contianer: Any) -> str:
    """
    :param recipe_contianer: recipe loaded as yaml with load_recipe_yaml_str_no_classes
    :return: recipe serialized into YAML with original class values re-added
    """
    updated_yaml_str = yaml.dump(recipe_contianer)

    # convert object dicts back to object declarations and return
    pattern = re.compile(
        r"OBJECT\.(?P<class_name>(?!.*\.)[a-zA-Z_][a-zA-Z^._0-9]+):( null)?"
    )
    return pattern.sub(r"!\g<class_name>", updated_yaml_str)


def update_recipe_variables(recipe_yaml_str: str, variables: Dict[str, Any]) -> str:
    """
    :param recipe_yaml_str: YAML string of a SparseML recipe
    :param variables: variables dictionary to update recipe top level variables with
    :return: given recipe with variables updated
    """

    container = load_recipe_yaml_str_no_classes(recipe_yaml_str)
    if not isinstance(container, dict):
        # yaml string does not create a dict, return original string
        return recipe_yaml_str

    for key in variables:
        if key not in container:
            _LOGGER.warning(
                f"updating recipe variable {key} but {key} is not currently "
                "set in existing recipe. This change may have no impact on the recipe "
                "modifiers"
            )

    container.update(variables)
    return rewrite_recipe_yaml_string_with_classes(container)


def evaluate_recipe_yaml_str_equations(recipe_yaml_str: str) -> str:
    """
    :param recipe_yaml_str: YAML string of a SparseML recipe
    :return: the YAML string with any expressions based on valid
        metadata and recipe variables and operations
    """
    container = load_recipe_yaml_str_no_classes(recipe_yaml_str)
    if not isinstance(container, dict):
        # yaml string does not create a dict, return original string
        return recipe_yaml_str

    # validate and load remaining variables
    container, variables = _evaluate_recipe_variables(container)

    # update values nested in modifier lists based on the variables
    for key, val in container.items():
        if "modifiers" not in key:
            continue
        container[key] = _maybe_evaluate_yaml_object(val, variables)

    return rewrite_recipe_yaml_string_with_classes(container)


def is_eval_string(val: str) -> bool:
    return val.startswith("eval(") and val.endswith(")")


def _maybe_evaluate_recipe_equation(
    val: str,
    variables: Dict[str, Union[int, float]],
) -> Union[str, float, int]:
    if is_eval_string(val):
        is_eval_str = True
        val = val[5:-1]
    else:
        return val

    evaluated_val = restricted_eval(val, variables)

    if is_eval_str and not isinstance(evaluated_val, (int, float)):
        raise RuntimeError(
            "eval expressions in recipes must evaluate to a float or int"
        )

    return evaluated_val


def _evaluate_recipe_variables(
    recipe_dict: Dict[str, Any],
) -> Tuple[Dict[str, Any], Dict[str, Union[int, float]]]:
    valid_variables = {}
    prev_num_variables = -1

    while prev_num_variables != len(valid_variables):
        prev_num_variables = len(valid_variables)

        for name, val in recipe_dict.items():
            if name in valid_variables:
                continue

            if isinstance(val, (int, float)):
                valid_variables[name] = val

            if not isinstance(val, str):
                # only parse string values
                continue

            try:
                val = _maybe_evaluate_recipe_equation(val, valid_variables)
            except UnknownVariableException:
                # dependant variables maybe not evaluated yet
                continue

            if isinstance(val, (int, float)):
                # update variable value and add to valid vars
                recipe_dict[name] = val
                valid_variables[name] = val

    # check that all eval statements have been evaluated
    for name, val in recipe_dict.items():
        if isinstance(val, str) and is_eval_string(val):
            raise RuntimeError(
                f"Unable to evaluate expression: {val}. Check if any dependent "
                "variables form a cycle or are not defined"
            )

    return recipe_dict, valid_variables


def _maybe_evaluate_yaml_object(
    obj: Any, variables: Dict[str, Union[int, float]]
) -> Any:
    if isinstance(obj, str):
        return _maybe_evaluate_recipe_equation(obj, variables)
    elif isinstance(obj, list):
        return [_maybe_evaluate_yaml_object(val, variables) for val in obj]
    elif isinstance(obj, dict):
        return {
            key: _maybe_evaluate_yaml_object(val, variables) for key, val in obj.items()
        }
    else:
        return obj


def _maybe_parse_number(val: str) -> Union[str, float, int]:
    try:
        return int(val)
    except Exception:
        try:
            return float(val)
        except Exception:
            return val
