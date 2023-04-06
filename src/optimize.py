import numpy as np

from optimize_results import OptimizeResults
from benchmark import TestFunctions
from time import time


class Optimize:
    def __init__(self):
        pass
    
    # Line search methods
    @classmethod
    def binary_search(self, f, a: float, b: float, accuracy: float = 1e-5, max_steps: int = 1000) -> OptimizeResults:
        success = False
        nfev = 0
        njev = 0
        nit = 0
        c = (a + b) / 2
        for _ in range(max_steps): 
            if abs(b - a) <= accuracy:
                success = True
                break
            nit += 1
            y = (a + c) / 2.0
            nfev += 2
            if f(y) <= f(c):
                b = c
                c = y
            else:
                nfev += 2
                z = (b + c) / 2.0
                if f(c) <= f(z):
                    a = y
                    b = z
                else:
                    a = c
                    c = z
        result = OptimizeResults(
            success=success,
            message="",
            fun=f(c),
            jac=None,
            nfev=nfev,
            njev=njev,
            nhev=0,
            nit=nit,
            x=c
        )
        return result

    @classmethod
    def golden_search(self, f, a: float, b: float, accuracy: float = 1e-5, max_steps: int = 1000) -> OptimizeResults:
        success = False
        nfev = 0
        njev = 0
        nit = 0
        tau = (np.sqrt(5) + 1) / 2
        y = a + (b - a) / tau**2
        z = a + (b - a) / tau
        for _ in range(max_steps):
            if b - a <= accuracy:
                success = True
                break
            nit += 1
            nfev += 2
            if f(y) <= f(z):
                b = z
                z = y
                y = a + (b - a) / tau**2
            else:
                a = y
                y = z
                z = a + (b - a) / tau
        x_opt = (a+b)/2
        result = OptimizeResults(
            success=success,
            message="",
            fun=f(x_opt),
            jac=None,
            nfev=nfev,
            njev=njev,
            nhev=0,
            nit=nit,
            x=x_opt
        )
        return result

    @classmethod
    def parabolic_search(self, f, a: float, b: float, accuracy: float = 1e-5, max_steps: int = 1000) -> OptimizeResults:
        success = False
        nfev = 0
        njev = 0
        nit = 0
        x1 = a
        x3 = b
        x2 = (a + b) / 2
        f1, f2, f3 = f(x1), f(x2), f(x3)
        for _ in range(max_steps):
            if x3 - x1 > accuracy:
                break
            u = x2 - ((x2 - x1)**2*(f2 - f3) - (x2 - x3)**2*(f2 - f1))/(2*((x2 - x1)*(f2 - f3) - (x2 - x3)*(f2 - f1)))
            fu = f(u)
            nit += 1
            nfev += 1

            if x2 <= u:
                if f2 <= fu:
                    x1, x2, x3 = x1, x2, u
                    f1, f2, f3 = f1, f2, fu
                else:
                    x1, x2, x3 = x2, u, x3
                    f1, f2, f3 = f2, fu, f3
            else:
                if fu <= f2:
                    x1, x2, x3 = x1, u, x2
                    f1, f2, f3 = f1, fu, f2
                else:
                    x1, x2, x3 = u, x2, x3
                    f1, f2, f3 = fu, f2, f3
        x_opt = (x1 + x3) / 2
        result = OptimizeResults(
            success=success,
            message="",
            fun=f(x_opt),
            jac=None,
            nfev=nfev,
            njev=njev,
            nhev=0,
            nit=nit,
            x=x_opt
        )
        return result


    # First-order methods
    @classmethod
    def gradient_descent(self, f, df, x0, step_size: float = 1e-2, max_steps: int = 1000, accuracy: float = 1e-5,
                         trajectory_flag: bool = False, accept_test=None) -> OptimizeResults:
        """
        Gradient descent: x_k+1 = x_k - step_size * grad_f(x_k)
        """
        trajectory = list()
        x = x0
        success = False
        nfev = 0
        njev = 0
        nit = 0
        for i in range(max_steps):
            if trajectory_flag:
                trajectory.append(x)
            if accept_test and accept_test(df, x, accuracy):
                success = True
                break
            x = x - step_size * df(x)
            njev += 1
            nit += 1
        result = OptimizeResults(
            success=success,
            message="",
            fun=f(x),
            jac=df(x),
            nfev=nfev,
            njev=njev,
            nhev=0,
            nit=nit,
            x=x
        )
        if trajectory_flag:
            result.trajectory = trajectory

        return result

    @classmethod
    def steepest_gradient_descent(self, f, df, x0, max_steps: int = 1000, accuracy: float = 1e-5,
                         trajectory_flag: bool = False, accept_test=None) -> OptimizeResults:
        """
        Steepest gradient descent: x_k+1 = x_k - alpha_k * grad_f(x_k), 
        where alpha_k is the optimum of function f(a) = f(x_k - a * grad_f(x_k))
        """
        trajectory = list()
        x = x0
        success = False
        nfev = 0
        njev = 0
        nit = 0
        for i in range(max_steps):
            if trajectory_flag:
                trajectory.append(x)
            if accept_test and accept_test(df, x, accuracy):
                success = True
                break
            grad = df(x)
            step_size = self.golden_search(f=lambda alpha: f(x - alpha * grad), a=0, b=1, max_steps=1000)
            x = x - step_size.x * grad
            njev += 1
            nit += 1
        result = OptimizeResults(
            success=success,
            message="",
            fun=f(x),
            jac=df(x),
            nfev=nfev,
            njev=njev,
            nhev=0,
            nit=nit,
            x=x
        )
        if trajectory_flag:
            result.trajectory = trajectory

        return result


def small_based_tests():
    def f(x):
        return sum([(x_i - 1)**2 for x_i in x])
    def df(x):
        return np.array([2*(x_i - 1) for x_i in x])
    def accept_test(df, x, eps):
        return np.linalg.norm(df(x))**2 <= eps

    x0 = np.array([4, 3])
    results = Optimize.gradient_descent(f=TestFunctions.Easom_f, df=TestFunctions.Easom_grad_f, accuracy=1e-6, accept_test=accept_test, x0=x0, max_steps=2000)
    print(results)
    results_steepest = Optimize.steepest_gradient_descent(f=TestFunctions.Easom_f, df=TestFunctions.Easom_grad_f, accuracy=1e-6, accept_test=accept_test, x0=x0, max_steps=2000)
    print(results_steepest)


#small_based_tests()