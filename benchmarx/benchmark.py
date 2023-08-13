import jaxopt
import jax
import jax.numpy as jnp

import time
import logging
from typing import List, Dict

from benchmarx.problem import Problem
import benchmarx.methods as _methods
import benchmarx.metrics as _metrics
from benchmarx.benchmark_result import BenchmarkResult
from benchmarx.custom_optimizer import CustomOptimizer

from benchmarx.ProxGD_custom_linesearch import GradientDescentCLS
from benchmarx.plotter import Plotter


class Benchmark:
    """
    A class that provides the benchmarking of different optimization
    methods on a given problem (like Problem object).


    Note: nfev, njev, nhev metrics aoutomaticly disable jax.jit.
    """

    runs: int = 1  # the number of runs of each method
    problem: Problem = None  # Problem to solve
    methods: List[Dict[str, Dict[str, any]]] = None  # Methods for benchmarking
    available_built_in_methods: List[str] = None  # method's keywords.
    # If you want to call a method from the jaxopt,
    # the name of the method must begin with one of these keywords.
    str_metrics_to_track: List[str]  # subset of _metrics.Metrics.metrics_to_track
    custom_metrics_to_track: List[_metrics.CustomMetric]  # your own custom metrics
    aval_linesearch_str = ["armijo", "goldstein", "strong-wolfe", "wolfe"]

    def __init__(
        self,
        problem: Problem,
        methods: List[Dict[str, Dict[str, any]]],
        metrics: List[str | _metrics.CustomMetric], # metrics to track
        runs: int = 1,
    ) -> None:
        """
        problem: Problem class object (or inheritor)
        methods: List[Dict[str, Dict[str, any]]] or List[Dict[str, CustomOptimizer]], methods for benchmarking
        metrics: List[str | _metrics.CustomMetric], metrics to track (see metrics.Metrics)
        runc: int, number of runs
        """
        self.runs = runs
        self.problem = problem
        self.methods = methods
        self.available_built_in_methods = _methods.available_built_in_methods
        
        self.str_metrics_to_track = [metric for metric in metrics if isinstance(metric, str)]
        _metrics.Metrics.check_metrics_to_track(
            metrics_to_check=self.str_metrics_to_track
        )

        self.str_metrics_to_track = _metrics.Metrics.fix_metrics_to_track(
            metrics_to_fix=self.str_metrics_to_track
        )
        self.custom_metrics_to_track = [
            metric for metric in metrics if isinstance(metric, _metrics.CustomMetric)
        ]

        self.nfev_global = 0    # number of objective function evaluations on the current iteration
        self.njev_global = 0    # number of objective function gradient evaluations on the current iteration
        self.nhev_global = 0    # number of objective function hessian evaluations on the current iteration
        


    def _check_linesearch(self, ls_str: str, method: str):
        # TODO: 'steepest' for QuadraticProblem!
        if method.startswith("GRADIENT_DESCENT"):
            return ls_str in ["armijo", "goldstein", "strong-wolfe", "wolfe"]
        elif method.startswith("BFGS") or method.startswith("LBFGS"):
            return ls_str in [
                "armijo",
                "goldstein",
                "strong-wolfe",
                "wolfe",
            ] or ls_str in ["backtracking", "zoom", "hager-zhang"]

        return False

    def __run_solver(
        self, 
        solver, 
        x_init,
        *args, 
        **kwargs
    ) -> Dict[str, List[any]]:
        """
        A layer for pulling the necessary information according to metrics
        as the "method" solver works (solver like jaxopt.GradientDescent obj
        or or an heir to the CustomOptimizer class)
        """
        # set nfev, njev and nhev to 0 at the begining of method
        self.nfev_global = 0
        self.njev_global = 0
        self.nhev_global = 0

        count_calls = "nfev" in self.str_metrics_to_track or "njev" in self.str_metrics_to_track or "nhev" in self.str_metrics_to_track

        custom_method_flag = issubclass(type(solver), CustomOptimizer)
        # cls = hasattr(solver, 'linesearch_custom')
        result = dict()
        state = solver.init_state(x_init, *args, **kwargs)
        sol = x_init
        if custom_method_flag and sol is None:
            sol = solver.x_init

        x_prev = sol

        @jax.jit
        def jitted_update(sol, state):
            # logging.warning(f'Function \"jitted_update\" doesn\'t use jax.jit.')
            return solver.update(sol, state, *args, **kwargs)

        def update(sol, state):
            return solver.update(sol, state, *args, **kwargs)

        def stop_criterion(err, tol):
            return err < tol

        tol = 0

        if not custom_method_flag and "tol" in kwargs:
            tol = kwargs["tol"]

        start_time = time.time()


        iters_total = 0
        for i in range(solver.maxiter):
            if i > 0:
                iters_total = i + 1
                if not custom_method_flag and stop_criterion(state.error, tol):
                    break
                if custom_method_flag and solver.stop_criterion(sol, state):
                    break

            if isinstance(sol, float):
                sol = jnp.array([sol])
            
            # metrics to track as method works: ["x", "nfev", "nhev", "njev", "time"]
            # "x" is always in self.str_metrics_to_track
            if not "x" in result:
                result["x"] = [sol]
            else:
                result["x"].append(sol)

            # "nit" is always in self.str_metrics_to_track
            if not "nit" in result:
                result["nit"] = [1]
            else:
                result["nit"][0] += 1
            

            if custom_method_flag or count_calls:
                sol, state = update(sol, state)
            else:
                sol, state = jitted_update(sol, state)
            
            if "nfev" in self.str_metrics_to_track:
                if "nfev" not in result:
                    result["nfev"] = [self.nfev_global]
                else:
                    result["nfev"].append(self.nfev_global)

            if "njev" in self.str_metrics_to_track:
                if "njev" not in result:
                    result["njev"] = [self.njev_global]
                else:
                    result["njev"].append(self.njev_global)

            if "nhev" in self.str_metrics_to_track:
                # in progress
                if "nhev" not in result:
                    result["nhev"] = [self.nhev_global]
                else:
                    result["nhev"].append(self.nhev_global)
            
            if "time" in self.str_metrics_to_track:
                if not "time" in result:
                    result["time"] = [time.time() - start_time]
                else:
                    result["time"].append(time.time() - start_time)
            
            x_prev = sol

        # metrics to track at the end
        for i in range(iters_total):
            sol = result["x"][i]
            # objective function values
            if "f" in self.str_metrics_to_track:
                if not "f" in result:
                    result["f"] = [self.problem.f(sol)]
                else:
                    result["f"].append(self.problem.f(sol))
            
            # gradient of the objective function
            if "grad" in self.str_metrics_to_track:
                grad_val = self.problem.grad(sol) if hasattr(self.problem, "grad") else jax.grad(self.problem.f)(sol)
                if not "grad" in result:
                    result["grad"] = [grad_val]
                else:
                    result["grad"].append(grad_val)

            # custom metrics moment
            for custom_metric in self.custom_metrics_to_track:
                if i % custom_metric.step == 0:
                    if not custom_metric.label in result:
                        result[custom_metric.label] = [custom_metric.func(sol)]
                    else:
                        result[custom_metric.label].append(custom_metric.func(sol))

        return result
    
    def traced_objective_function(self, x):
        self.nfev_global += 1
        return self.problem.f(x)
    
    def traced_gradient_function(self, x):
        self.njev_global += 1
        if hasattr(self.problem, "grad"):
            return self.problem.grad(x)
        return jax.grad(self.problem.f)(x)
    
    def tracked_objective_and_gradient(self, x, *args, **kwargs):
        return self.traced_objective_function(x), self.traced_gradient_function(x)

    def run(self) -> BenchmarkResult:
        res = BenchmarkResult(
            problem=self.problem, 
            methods=list()
        )
        data = dict()
        data[self.problem] = dict()
        # methods: list[dict[method(str) : dict[str:any]]]
        for item in self.methods:
            for method, params in item.items():
                if not isinstance(params, CustomOptimizer):
                    # data: dict[Problem, dict[method(str), dict[str, list[any]]]]

                    # ======= custom line search =======
                    # A class jaxopt.BacktrackingLineSearch object or str is expected.
                    # For Gradient Descent: params['linesearch'] in ['wolfe', 'strong-wolfe', 'armijo', 'goldstein']
                    # For (L)BFGS: params['linesearch'] must be str from
                    # ['backtracking', 'zoom', 'hager-zhang'] or ['wolfe', 'strong-wolfe', 'armijo', 'goldstein'].
                    if not _methods.check_method([method]):
                        continue

                    cls = "linesearch" in params

                    if method.startswith("GRADIENT_DESCENT"):
                        logging.info("Default gradient descent")
                        res.methods.append(method)
                        x_init = None
                        label = "jaxopt.GradientDescent"
                        seed = str(self.problem.seed)
                        if "x_init" in params:
                            x_init = params["x_init"]
                            params.pop("x_init")
                        if "label" in params:
                            label = params["label"]
                            params.pop("label")
                        if "seed" in params:
                            seed = params["seed"]
                            params.pop("seed")
                        runs_dict = dict()
                        solver = None
                        if cls:
                            ls = params["linesearch"]
                            params.pop("linesearch")
                            if "condition" in params:
                                condition = params["condition"]
                                params.pop("condition")
                            if isinstance(ls, str):
                                if ls == "backtracking":
                                    if condition in [
                                        "wolfe",
                                        "strong-wolfe",
                                        "armijo",
                                        "goldstein",
                                    ]:
                                        ls_obj = jaxopt.BacktrackingLineSearch(
                                            fun=self.tracked_objective_and_gradient,
                                            value_and_grad=True,
                                            maxiter=20,
                                            condition=condition,
                                            decrease_factor=0.8,
                                        )
                                    else:
                                        err_msg = f"Unknown condition {condition}"
                                        logging.critical(err_msg)
                                        exit(1)
                                elif ls == "hager-zhang":
                                    ls_obj = jaxopt.HagerZhangLineSearch(
                                        fun=self.tracked_objective_and_gradient,
                                        value_and_grad=True,
                                    )
                                else:
                                    err_msg = f"Unknown line search {ls}"
                                    logging.critical(err_msg)
                                    exit(1)
                                solver = GradientDescentCLS(
                                    fun=self.tracked_objective_and_gradient,
                                    value_and_grad=True, 
                                    **params
                                )
                                solver.linesearch_custom = ls_obj
                            elif isinstance(ls, jaxopt.BacktrackingLineSearch):
                                solver = GradientDescentCLS(
                                    fun=self.tracked_objective_and_gradient,
                                    value_and_grad=True,
                                    **params
                                )
                                solver.linesearch_custom = ls
                            else:
                                err_msg = f"Unknown linesearch {ls}"
                                logging.critical(err_msg)
                                exit(1)
                        else:
                            solver = jaxopt.GradientDescent(
                                fun=self.tracked_objective_and_gradient,
                                value_and_grad=True,
                                **params
                            )

                        for run in range(self.runs):
                            if run % 10 == 0:
                                logging.info(f"#{run} run...")
                            sub = self.__run_solver(
                                solver=solver,
                                x_init=x_init,
                                **params,
                            )
                            runs_dict[f"run_{run}"] = sub
                        params["x_init"] = x_init
                        params["label"] = label
                        params["seed"] = seed
                        data[self.problem][method] = {
                            "hyperparams": params,
                            "runs": runs_dict,
                        }

                    elif method.startswith("BFGS"):
                        logging.info("BFGS (jaxopt built-in)")
                        res.methods.append(method)
                        x_init = None
                        label = "jaxopt.BFGS"
                        seed = str(self.problem.seed)
                        if "x_init" in params:
                            x_init = params["x_init"]
                            params.pop("x_init")
                        if "label" in params:
                            label = params["label"]
                            params.pop("label")
                        if "seed" in params:
                            seed = params["seed"]
                            params.pop("seed")
                        runs_dict = dict()
                        soler = None
                        if cls:
                            new_linesearch = "zoom"
                            new_condition = "stron-wolfe"
                            ls = params["linesearch"]
                            params.pop("linesearch")
                            cond = ""
                            if "condition" in params:
                                cond = params["condition"]
                                params.pop("condition")
                            if isinstance(ls, str) and self._check_linesearch(
                                ls, method
                            ):
                                if ls in ["backtracking", "zoom", "hager-zhang"]:
                                    new_linesearch = ls
                                else:
                                    err_msg = f"Unknown line search '{ls}'. zoom line search will be used instead of {ls}."
                                    logging.warning(err_msg)
                                if cond in [
                                    "wolfe",
                                    "strong-wolfe",
                                    "armijo",
                                    "goldstein",
                                ]:
                                    new_condition = cond
                                else:
                                    err_msg = f"Unknown condition '{cond}'. strong-wolfe condition will be used instead if {cond}"
                                    logging.warning(err_msg)
                            else:
                                err_msg = f"For BFGS parameter 'linesearch' must be string from {['wolfe', 'strong-wolfe', 'armijo', 'goldstein']}(condition) or {['backtracking', 'zoom', 'hager-zhang']} (linesearch)"
                                logging.critical(err_msg)

                            solver = jaxopt.BFGS(
                                fun=self.tracked_objective_and_gradient,
                                value_and_grad=True,
                                linesearch=new_linesearch,
                                condition=new_condition,
                                **params,
                            )
                        else:
                            solver = jaxopt.BFGS(
                                fun=self.tracked_objective_and_gradient,
                                value_and_grad=True,
                                **params)

                        for run in range(self.runs):
                            if run % 10 == 0:
                                logging.info(f"#{run} run...")
                            sub = self.__run_solver(
                                solver=solver,
                                x_init=x_init,
                                **params,
                            )
                            runs_dict[f"run_{run}"] = sub
                        params["x_init"] = x_init
                        params["label"] = label
                        params["seed"] = seed
                        data[self.problem][method] = {
                            "hyperparams": params,
                            "runs": runs_dict,
                        }

                    elif method.startswith("LBFGS"):
                        logging.info("LBFGS (jaxopt built-in)")
                        res.methods.append(method)
                        x_init = None
                        label = "jaxopt.LBFGS"
                        seed = str(self.problem.seed)
                        if "x_init" in params:
                            x_init = params["x_init"]
                            params.pop("x_init")
                        if "label" in params:
                            label = params["label"]
                            params.pop("label")
                        if "seed" in params:
                            seed = params["seed"]
                            params.pop("seed")
                        runs_dict = dict()
                        for run in range(self.runs):
                            if cls:
                                new_linesearch = "zoom"
                                new_condition = "stron-wolfe"
                                ls = params["linesearch"]
                                params.pop("linesearch")
                                cond = ""
                                if "condition" in params:
                                    cond = params["condition"]
                                    params.pop("condition")
                                if isinstance(ls, str) and self._check_linesearch(
                                    ls, method
                                ):
                                    if ls in ["backtracking", "zoom", "hager-zhang"]:
                                        new_linesearch = ls
                                    if cond in [
                                        "wolfe",
                                        "strong-wolfe",
                                        "armijo",
                                        "goldstein",
                                    ]:
                                        new_condition = cond
                                    else:
                                        err_msg = f"Unknown line search '{ls}', {cond}"
                                        logging.critical(err_msg)
                                        exit(1)
                                else:
                                    err_msg = f"For LBFGS parameter 'linesearch' must be string from {['wolfe', 'strong-wolfe', 'armijo', 'goldstein']}(condition) or {['backtracking', 'zoom', 'hager-zhang']} (linesearch)"
                                    logging.critical(err_msg)

                                solver = jaxopt.LBFGS(
                                    fun=self.tracked_objective_and_gradient,
                                    value_and_grad=True,
                                    linesearch=new_linesearch,
                                    condition=new_condition,
                                    **params,
                                )
                            else:
                                solver = jaxopt.LBFGS(
                                    fun=self.tracked_objective_and_gradient,
                                    value_and_grad=True, 
                                    **params)
                            sub = self.__run_solver(
                                solver=solver,
                                x_init=x_init,
                                **params,
                            )
                            runs_dict[f"run_{run}"] = sub
                        params["x_init"] = x_init
                        params["label"] = label
                        params["seed"] = seed
                        data[self.problem][method] = {
                            "hyperparams": params,
                            "runs": runs_dict,
                        }

                    elif method.startswith("ArmijoSGD"):
                        logging.info("ArmijoSGD (jaxopt built-in)")
                        res.methods.append(method)
                        x_init = None
                        label = "jaxopt.ArmijoSGD"
                        seed = str(self.problem.seed)
                        if "x_init" in params:
                            x_init = params["x_init"]
                            params.pop("x_init")
                        if "label" in params:
                            label = params["label"]
                            params.pop("label")
                        if "seed" in params:
                            seed = params["seed"]
                            params.pop("seed")
                        runs_dict = dict()
                        solver = jaxopt.ArmijoSGD(
                            fun=self.tracked_objective_and_gradient,
                            value_and_grad=True, 
                            **params)
                        for run in range(self.runs):
                            if run % 10 == 0:
                                logging.info(f"#{run} run...")
                            sub = self.__run_solver(
                                solver=solver,
                                x_init=x_init,
                                **params,
                            )
                            runs_dict[f"run_{run}"] = sub
                        params["x_init"] = x_init
                        params["label"] = label
                        params["seed"] = seed
                        data[self.problem][method] = {
                            "hyperparams": params,
                            "runs": runs_dict,
                        }

                    elif method.startswith("PolyakSGD"):
                        logging.info("PolyakSGD (jaxopt built-in)")
                        res.methods.append(method)
                        x_init = None
                        label = "jaxopt.PolyakSGD"
                        seed = str(self.problem.seed)
                        if "x_init" in params:
                            x_init = params["x_init"]
                            params.pop("x_init")
                        if "label" in params:
                            label = params["label"]
                            params.pop("label")
                        if "seed" in params:
                            seed = params["seed"]
                            params.pop("seed")
                        runs_dict = dict()
                        solver = jaxopt.PolyakSGD(
                            fun=self.tracked_objective_and_gradient,
                            value_and_grad=True, 
                            **params)
                        for run in range(self.runs):
                            if run % 10 == 0:
                                logging.info(f"#{run} run...")
                            sub = self.__run_solver(
                                solver=solver,
                                x_init=x_init,
                                **params,
                            )
                            runs_dict[f"run_{run}"] = sub
                        params["x_init"] = x_init
                        params["label"] = label
                        params["seed"] = seed
                        data[self.problem][method] = {
                            "hyperparams": params,
                            "runs": runs_dict,
                        }

                else:
                    # params is custom_solver object now
                    custom_solver = params
                    logging.info("Custom method")
                    res.methods.append(method)
                    runs_dict = dict()
                    x_init = custom_solver.x_init
                    for run in range(self.runs):
                        if run % 10 == 0:
                            logging.info(f"#{run} run...")
                        sub = self.__run_solver(
                            solver=custom_solver,
                            x_init=x_init
                        )
                        runs_dict[f"run_{run}"] = sub
                    params_to_write = custom_solver.params
                    if "x_init" not in params_to_write:
                        params_to_write["x_init"] = x_init
                    params_to_write["label"] = custom_solver.label
                    params_to_write["seed"] = self.problem.seed
                    data[self.problem][method] = {
                        "hyperparams": params_to_write,
                        "runs": runs_dict,
                    }

        res.data = data
        return res
