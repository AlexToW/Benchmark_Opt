import jaxopt
import jax
import jax.numpy as jnp

import time
import logging

from problem import Problem
import methods as _methods

# from benchmark_target import BenchmarkTarget
import metrics as _metrics
from benchmark_result import BenchmarkResult
from problems.quadratic_problem import QuadraticProblem
import custom_optimizer

from ProxGD_custom_linesearch import GradientDescentCLS


class Benchmark:
    """
    A class that provides the benchmarking of different optimization
    methods on a given problem (like Problem object).
    """

    runs: int = 1       # the number of runs of each method
    problem: Problem = None  # Problem to solve
    methods: list[dict[str : dict[str:any]]] = None  # Methods for benchmarking
    available_built_in_methods: list[str] = None # method's keywords. 
    # If you want to call a method from the jaxopt, 
    # the name of the method must begin with one of these keywords.
    metrics: list[str] = None  # List of fields to include in BenchamrkResult
    aval_linesearch_str = ['armijo', 'goldstein', 'strong-wolfe', 'wolfe']
    def __init__(
        self,
        problem: Problem,
        methods: list[dict[str : dict[str:any]]],
        metrics: list[str],
        runs: int = 1
    ) -> None:
        self.runs = runs
        self.problem = problem
        methods_names = list()
        for item in methods:
            for name, params in item.items():
                methods_names.append(name)
        if not _methods.check_method(methods_names):
            exit(1)
        self.methods = methods
        self.available_built_in_methods = _methods.available_built_in_methods
        if not _metrics.check_metric(metrics):
            exit(1)
        self.metrics = metrics

    def _check_linesearch(self, ls_str):
        #TODO: 'steepest' for QuadraticProblem!
        #if isinstance(self.problem, QuadraticProblem):
        #    return ls_str == 'steepest' or ls_str in self.aval_linesearch_str
        return ls_str in self.aval_linesearch_str

    def __run_solver(
        self, solver, x_init, metrics: list[str], *args, **kwargs
    ) -> dict[str, list[any]]:
        """
        A layer for pulling the necessary information according to metrics
        as the "method" solver works (solver like jaxopt.GradientDescent obj
        or or an heir to the CustomOptimizer class)
        """
        custom_method = issubclass(type(solver), custom_optimizer.CustomOptimizer)
        #cls = hasattr(solver, 'linesearch_custom')
        result = dict()
        start_time = time.time()
        state = solver.init_state(x_init, *args, **kwargs)
        sol = x_init
        if custom_method and sol is None:
            sol = solver.x_init
        
        x_prev = sol

        @jax.jit
        def jitted_update(sol, state):
            return solver.update(sol, state, *args, **kwargs)
        
        def update(sol, state):
            return solver.update(sol, state, *args, **kwargs)


        def stop_criterion(err, tol):
            return err < tol

        tol = 1e-3
        
        if not custom_optimizer and 'tol' in kwargs:
            tol = kwargs['tol']
        
        #print(tol)
        for i in range(solver.maxiter):
            if i > 0:
                if not custom_method and stop_criterion(state.error, tol):
                    break
                if custom_method and solver.stop_criterion(sol, state):
                    break

            if "history_x" in metrics:
                if not "history_x" in result:
                    result["history_x"] = [sol]
                else:
                    result["history_x"].append(sol)
            if "history_f" in metrics:
                if not "history_f" in result:
                    result["history_f"] = [self.problem.f(sol)]
                else:
                    result["history_f"].append(self.problem.f(sol))
            if "history_df" in metrics:
                if not "history_df" in result:
                    result["history_df"] = [jax.grad(self.problem.f)(sol)]
                else:
                    result["history_df"].append(jax.grad(self.problem.f)(sol))
            if "nit" in metrics:
                if not "nit" in result:
                    result["nit"] = [1]
                else:
                    result["nit"][0] += 1
            if "nfev" in metrics:
                # IDK
                pass
            if "njev" in metrics:
                # IDK
                pass
            if "nhev" in metrics:
                # IDK
                pass
            if "errors" in metrics:
                if not "errors" in result:
                    result["errors"] = [state.error]
                else:
                    result["errors"].append(state.error)
            x_prev = sol
            if custom_method:
                sol, state = update(sol, state)
            else:
                sol, state = jitted_update(sol, state)
        duration = time.time() - start_time
        if "time" in metrics:
            result["time"] = [duration]

        return result

    def run(self, user_method = None) -> BenchmarkResult:
        res = BenchmarkResult(problem=self.problem, methods=list(), metrics=self.metrics)
        data = dict()
        data[self.problem] = dict()
        # methods: list[dict[method(str) : dict[str:any]]]
        for item in self.methods:
            for method, params in item.items():
                # data: dict[Problem, dict[method(str), dict[str, list[any]]]]
                
                #======= custom line search =======
                # A class jaxopt.BacktrackingLineSearch object or str is expected.
                cls = 'linesearch' in params
                linesearch = None
                ls_str = ''
                ls_condition = ''
                if cls:
                    tmp_ls = params['linesearch']
                    if isinstance(tmp_ls, str):
                        if method.startswith('BFGS') or method.startswith('LBFGS'):
                            if tmp_ls in ['backtracking', 'zoom', 'hager-zhang']:
                                ls_str = tmp_ls
                            elif self._check_linesearch(tmp_ls):
                                ls_condition = tmp_ls
                            else:
                                error_str = f'Bad \'linesearch\' argument: must be BacktrackingLineSearch obj or str {self.aval_linesearch_str}, or \'steepest\' for QuadraticProblem, or {["backtracking", "zoom", "hager-zhang"]}'
                                logging.critical(error_str)
                                exit(1)
                        if not self._check_linesearch(tmp_ls):
                            error_str = f'Bad \'linesearch\' argument: must be BacktrackingLineSearch obj or str {self.aval_linesearch_str}, or \'steepest\' for QuadraticProblem'
                            logging.critical(error_str)
                            exit(1)
                        ls_str = tmp_ls
                        linesearch = jaxopt.BacktrackingLineSearch(fun=self.problem.f, maxiter=20, condition=tmp_ls,
                                decrease_factor=0.8)
                    elif isinstance(tmp_ls, jaxopt.BacktrackingLineSearch):
                        linesearch = tmp_ls
                    else:
                        error_str = f'Bad \'linesearch\' argument: must be BacktrackingLineSearch obj or str {self.aval_linesearch_str}, or \'steepest\' for QuadraticProblem'
                        logging.critical(error_str)
                        exit(1)
                    params.pop('linesearch')

                # Now linesearch is jaxopt.BacktrackingLineSearch object!!!
                
                if method.startswith('GRADIENT_DESCENT'):
                    logging.info('Default gradient descent')
                    res.methods.append(method)
                    x_init = None
                    label = 'jaxopt.GradientDescent'
                    seed = str(self.problem.seed)
                    if 'x_init' in params:
                        x_init = params['x_init']
                        params.pop('x_init')
                    if 'label' in params:
                        label = params['label']
                        params.pop('label')
                    if 'seed' in params:
                        seed = params['seed']
                        params.pop('seed')
                    runs_dict = dict()
                    for run in range(self.runs):
                        if cls:
                            solver = GradientDescentCLS(fun=self.problem.f, **params)
                            solver.linesearch_custom = linesearch
                        else:
                            solver = jaxopt.GradientDescent(fun=self.problem.f, **params)
                        sub = self.__run_solver(solver=solver, x_init=x_init, metrics=self.metrics, **params)    
                        runs_dict[f'run_{run}'] = sub
                    params['x_init'] = x_init
                    params['label'] = label
                    params['seed'] = seed
                    data[self.problem][method] = {'hyperparams': params, 'runs': runs_dict}

                elif method.startswith('BFGS'):
                    logging.info('BFGS (jaxopt built-in)')
                    res.methods.append(method)
                    x_init = None
                    label = 'jaxopt.BFGS'
                    seed = str(self.problem.seed)
                    if 'x_init' in params:
                        x_init = params['x_init']
                        params.pop('x_init')
                    if 'label' in params:
                        label = params['label']
                        params.pop('label')
                    if 'seed' in params:
                        seed = params['seed']
                        params.pop('seed')
                    runs_dict = dict()
                    for run in range(self.runs):
                        if cls:
                            if ls_str != '' and ls_condition != '':
                                solver = jaxopt.BFGS(fun=self.problem.f, linesearch=ls_str, condition=ls_str, **params)
                            if ls_str == '' and ls_condition != '':
                                solver = jaxopt.BFGS(fun=self.problem.f, linesearch=ls_str, condition=ls_str, **params)
                        else:
                            solver = jaxopt.BFGS(fun=self.problem.f, **params)
                        sub = self.__run_solver(solver=solver, x_init=x_init, metrics=self.metrics, **params)    
                        runs_dict[f'run_{run}'] = sub
                    params['x_init'] = x_init
                    params['label'] = label
                    params['seed'] = seed
                    data[self.problem][method] = {'hyperparams': params, 'runs': runs_dict}

                elif method.startswith('LBFGS'):
                    logging.info('LBFGS (jaxopt built-in)')
                    res.methods.append(method)
                    x_init = None
                    label = 'jaxopt.LBFGS'
                    seed = str(self.problem.seed)
                    if 'x_init' in params:
                        x_init = params['x_init']
                        params.pop('x_init')
                    if 'label' in params:
                        label = params['label']
                        params.pop('label')
                    if 'seed' in params:
                        seed = params['seed']
                        params.pop('seed')
                    runs_dict = dict()
                    for run in range(self.runs):
                        if cls:
                            solver = jaxopt.LBFGS(fun=self.problem.f, condition=ls_str, **params)
                        else:
                            solver = jaxopt.LBFGS(fun=self.problem.f, **params)
                        sub = self.__run_solver(solver=solver, x_init=x_init, metrics=self.metrics, **params)    
                        runs_dict[f'run_{run}'] = sub
                    params['x_init'] = x_init
                    params['label'] = label
                    params['seed'] = seed
                    data[self.problem][method] = {'hyperparams': params, 'runs': runs_dict}



                elif user_method is not None:
                    logging.info('Custom method')
                    res.methods.append(method)
                    x_init = None
                    if 'x_init' in params:
                        x_init = jnp.array(params['x_init'])
                        params.pop('x_init')
                    runs_dict = dict()
                    for run in range(self.runs):
                        sub = self.__run_solver(solver=user_method, metrics=self.metrics, x_init=x_init, **params)
                        runs_dict[f'run_{run}'] = sub
                    params_to_write = user_method.params
                    if 'x_init' not in params_to_write:
                        params_to_write['x_init'] = user_method.x_init
                    params_to_write['label'] = user_method.label
                    params_to_write['seed'] = self.problem.seed
                    data[self.problem][method] = {'hyperparams': params_to_write, 'runs': runs_dict}

        res.data = data
        return res


def test_local():
    from problems.quadratic_problem import QuadraticProblem

    n = 2
    x_init = jnp.array([1.0, 1.0])
    problem = QuadraticProblem(n=n)
    benchamrk = Benchmark(
        problem=problem,
        methods=[
            {
                'GRADIENT_DESCENT_const_step': {
                    'x_init' : x_init,
                    'tol': 1e-2,
                    'maxiter': 11,
                    'stepsize' : 1e-2
                }
            },
            {
                'GRADIENT_DESCENT_adaptive_step': {
                    'x_init' : x_init,
                    'tol': 1e-2,
                    'maxiter': 11,
                    'stepsize' : lambda iter_num: 1 / (iter_num + 20)
                }
            },
            {
                'BFGS_strong_wolfe': {
                    'x_init' : x_init,
                    'tol': 1e-2,
                    'maxiter': 11,
                    'linesearch': 'strong-wolfe'
                }
            },
            {
                'BFGS_armijo': {
                    'x_init' : x_init,
                    'tol': 1e-2,
                    'maxiter': 11,
                    'linesearch': 'armijo'
                }
            }
        ],
        metrics=[
            "nit",
            "history_x",
            "history_f",
        ],
    )
    result = benchamrk.run()
    result.save("GD_quadratic.json")


if __name__ == "__main__":
    test_local()
