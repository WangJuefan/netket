# Copyright 2019 The Simons Foundation, Inc. - All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import jax
from functools import partial

import numpy as _np
from jax import numpy as jnp
from jax.tree_util import (
    tree_flatten,
    tree_unflatten,
    tree_map,
    tree_multimap,
    tree_leaves,
)

from typing import Callable, Tuple, Any, Union

from .utils import is_complex, tree_leaf_iscomplex, eval_shape


# _grad_CC, _RR and _RC are the batched gradient functions for machines going
# from R -> C, R->R and R->C. Ditto for vjp
# Thee reason why R->C is more complicated is that it splits the calculation
# into the real and complex part in order to be more efficient.


def vjp_cc(
    fun: Callable, *primals, has_aux: bool = False, conjugate: bool = False
) -> Union[Tuple[Any, Callable], Tuple[Any, Callable, Any]]:
    if has_aux:
        out, _vjp_fun, aux = jax.vjp(fun, *primals, has_aux=True)
    else:
        out, _vjp_fun = jax.vjp(fun, *primals, has_aux=False)

    if conjugate:

        def vjp_fun(ȳ):
            """
            function computing the vjp product for a conjugated C->C function
            """
            return tree_map(jnp.conjugate, _vjp_fun(ȳ))

    else:
        vjp_fun = _vjp_fun

    if has_aux:
        return out, vjp_fun, aux
    else:
        return out, vjp_fun


def vjp_rr(
    fun: Callable, *primals, has_aux: bool = False, conjugate: bool = False
) -> Union[Tuple[Any, Callable], Tuple[Any, Callable, Any]]:
    if has_aux:
        primals_out, _vjp_fun, aux = jax.vjp(fun, *primals, has_aux=True)
    else:
        primals_out, _vjp_fun = jax.vjp(fun, *primals, has_aux=False)

    def vjp_fun(ȳ):
        """
        function computing the vjp product for a R->R function.
        """
        if not is_complex(ȳ):
            out = _vjp_fun(ȳ)
        else:
            out_r = _vjp_fun(ȳ.real)
            out_i = _vjp_fun(-ȳ.imag)
            if conjugate:
                out = tree_multimap(lambda re, im: re - 1j * im, out_r, out_i)
            else:
                out = tree_multimap(lambda re, im: re + 1j * im, out_r, out_i)

        return out

    if has_aux:
        return primals_out, vjp_fun, aux
    else:
        return primals_out, vjp_fun


def vjp_rc(
    fun: Callable, *primals, has_aux: bool = False, conjugate: bool = False
) -> Union[Tuple[Any, Callable], Tuple[Any, Callable, Any]]:
    if has_aux:

        def real_fun(*primals):
            val, aux = fun(pars, v)
            return val.real, aux

        def imag_fun(*primals):
            val, aux = fun(pars, v)
            return val.imag, aux

        vals_r, vjp_r_fun, aux = jax.vjp(real_fun, *primals, has_aux=True)
        vals_j, vjp_j_fun, _ = jax.vjp(imag_fun, *primals, has_aux=True)

    else:
        real_fun = lambda *primals: fun(*primals).real
        imag_fun = lambda *primals: fun(*primals).imag

        vals_r, vjp_r_fun = jax.vjp(real_fun, *primals, has_aux=False)
        vals_j, vjp_j_fun = jax.vjp(imag_fun, *primals, has_aux=False)

    primals_out = vals_r + 1j * vals_j

    def vjp_fun(ȳ):
        """
        function computing the vjp product for a R->C function.
        """
        ȳ_r = ȳ.real
        ȳ_j = ȳ.imag

        # val = vals_r + vals_j
        vr_jr = vjp_r_fun(ȳ_r)
        vj_jr = vjp_r_fun(ȳ_j)
        vr_jj = vjp_j_fun(ȳ_r)
        vj_jj = vjp_j_fun(ȳ_j)

        r = tree_multimap(
            lambda re, im: re - 1j * im,
            vr_jr,
            vj_jr,
        )
        i = tree_multimap(lambda re, im: re - 1j * im, vr_jj, vj_jj)
        out = tree_multimap(lambda re, im: re + 1j * im, r, i)

        if conjugate:
            out = tree_map(jnp.conjugate, out)

        return out

    if has_aux:
        return primals_out, vjp_fun, aux
    else:
        return primals_out, vjp_fun


#  This function dispatches to the right
def vjp(
    fun: Callable, *primals, has_aux: bool = False, conjugate: bool = False
) -> Union[Tuple[Any, Callable], Tuple[Any, Callable, Any]]:

    # output dtype
    out_shape = eval_shape(fun, *primals, has_aux=has_aux)

    if tree_leaf_iscomplex(primals):
        if is_complex(out_shape):  # C -> C
            return vjp_cc(fun, *primals, has_aux=has_aux, conjugate=conjugate)
        else:  # C -> R
            raise RuntimeError("C->R function detected, but not supported.")
    else:
        if is_complex(out_shape):  # R -> C
            return vjp_rc(fun, *primals, has_aux=has_aux, conjugate=conjugate)
        else:  # R -> R
            return vjp_rr(fun, *primals, has_aux=has_aux, conjugate=conjugate)
