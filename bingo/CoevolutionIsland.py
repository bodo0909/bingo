"""
Defines an island that has 3 populations and performs the simultaneous
evolution of a main population, and a fitness predictor population.  The third
population is a set of training individuals on which the quality of the fitness
predictors is judged.
This is loosely based on the work of Schmidt and Lipson 2008?
"""
import logging
import numpy as np

from .Island import Island

LOGGER = logging.getLogger(__name__)

class CoevolutionIsland(object):
    """
    Coevolution island with 3 populations
    solution_pop: the solutions to symbolic regression
    predictor_pop: sub sampling
    trainers: population of solutions which are used to train the predictors


    :param solution_training_data: training data that is used in the
                                   evaluation of fitness of the solution
                                   population
    :param solution_manipulator: a gene manipulator for the symbolic
                                 regression solution population
    :param predictor_manipulator: a gene manipulator for the fitness
                                  predictor population
    :param solution_pop_size: size of the solution population
    :param solution_cx: crossover probability for the solution population
    :param solution_mut: mutation probability for the solution population
    :param predictor_pop_size: size of the fitness predictor population
    :param predictor_cx: crossover probability for the fitness predictor
                         population
    :param predictor_mut: mutation probability for the fitness predictor
                          population
    :param predictor_ratio: approximate ratio of time spent on fitness
                            predictor calculations and the total
                            computation time
    :param predictor_update_freq: number of generations of the solution
                                  population after which the fitness
                                  predictor is updated
    :param trainer_pop_size: size of the trainer population
    :param trainer_update_freq: number of generations of the solution
                                population after which a new trainer is
                                added to the trainer population
    :param required_params: number of unique parameters that are required
                            in implicit (constant) symbolic regression
    :param verbose: True for extra output printed to screen
    """

    def __init__(self, solution_training_data, solution_manipulator,
                 predictor_manipulator, fitness_metric,
                 solution_pop_size=64, solution_cx=0.7, solution_mut=0.01,
                 solution_age_fitness=False,
                 predictor_pop_size=16, predictor_cx=0.5, predictor_mut=0.1,
                 predictor_ratio=0.1, predictor_update_freq=50,
                 trainer_pop_size=16, trainer_update_freq=50,
                 verbose=False):
        """
        Initializes coevolution island
        """
        self.verbose = verbose
        self.fitness_metric = fitness_metric
        self.solution_training_data = solution_training_data

        # check if fitness predictors are valid range
        if self.solution_training_data.size() < predictor_manipulator.max_index:
            predictor_manipulator.max_index = \
                self.solution_training_data.size()

        # initialize solution island
        self.solution_island = Island(solution_manipulator,
                                      self.solution_fitness_est,
                                      target_pop_size=solution_pop_size,
                                      cx_prob=solution_cx,
                                      mut_prob=solution_mut,
                                      age_fitness=solution_age_fitness)
        # initialize fitness predictor island
        self.predictor_island = Island(predictor_manipulator,
                                       self.predictor_fitness,
                                       target_pop_size=predictor_pop_size,
                                       cx_prob=predictor_cx,
                                       mut_prob=predictor_mut)
        self.predictor_update_freq = predictor_update_freq

        # initialize trainers
        self.trainers = []
        self.trainers_true_fitness = []
        for _ in range(trainer_pop_size):
            legal_trainer_found = False
            while not legal_trainer_found:
                ind = np.random.randint(0, solution_pop_size)
                sol = self.solution_island.pop[ind]
                true_fitness = self.solution_fitness_true(sol)
                legal_trainer_found = not np.isnan(true_fitness)
                for pred in self.predictor_island.pop:
                    if np.isnan(pred.fit_func(sol, self.fitness_metric,
                                              self.solution_training_data)):
                        legal_trainer_found = False
            self.trainers.append(self.solution_island.pop[ind].copy())
            self.trainers_true_fitness.append(true_fitness)
        self.trainer_update_freq = trainer_update_freq

        # computational balance
        self.predictor_ratio = predictor_ratio
        self.predictor_to_solution_eval_cost = len(self.trainers)

        # find best predictor for use as starting fitness
        # function in solution island
        self.best_predictor = self.predictor_island.best_indv().copy()

        # initial output
        if self.verbose:
            best_pred = self.best_predictor
            LOGGER.debug("P> " + str(self.predictor_island.age)\
                         + " " + str(best_pred.fitness)\
                         + " " + str(best_pred))
            self.solution_island.update_pareto_front()
            best_sol = self.solution_island.pareto_front[0]
            LOGGER.debug("S> " + str(self.solution_island.age)\
                         + " " + str(best_sol.fitness)\
                         + " " + str(best_sol.latexstring()))

    def solution_fitness_est(self, solution):
        """
        Estimated fitness for solution pop based on the best predictor

        :param solution: individual of the solution population for which the
                         fitness will be calculated
        :return: fitness, complexity
        """
        fit = self.best_predictor.fit_func(solution, self.fitness_metric,
                                           self.solution_training_data)
        return fit, solution.complexity()

    def predictor_fitness(self, predictor):
        """
        Fitness function for predictor population, based on the ability to
        accurately describe the true fitness of the trainer population

        :param predictor: predictor for which the fitness is assessed
        :return: fitness
        """
        err = 0.0
        for train, true_fit in zip(self.trainers, self.trainers_true_fitness):
            predicted_fit = predictor.fit_func(train, self.fitness_metric,
                                               self.solution_training_data)
            err += abs(true_fit - predicted_fit)
        return err/len(self.trainers)

    def solution_fitness_true(self, solution):
        """
        full calculation of fitness for solution population

        :param solution: individual of the solution population for which the
                         fitness will be calculated
        :return: fitness
        """

        # calculate fitness metric
        err = self.fitness_metric.evaluate_fitness(solution,
                                                   self.solution_training_data)

        return err

    def add_new_trainer(self):
        """
        Add/replace trainer to current trainer population.  The trainer which
        maximizes discrepancy between fitness predictors is chosen
        """
        s_best = self.solution_island.pop[0]
        max_variance = 0
        for sol in self.solution_island.pop:
            pfit_list = []
            for pred in self.predictor_island.pop:
                pfit_list.append(pred.fit_func(sol, self.fitness_metric,
                                               self.solution_training_data))
            try:
                variance = np.var(pfit_list)
            except (ArithmeticError, OverflowError, FloatingPointError,
                    ValueError):
                variance = np.nan
            if variance > max_variance:
                max_variance = variance
                s_best = sol.copy()
        location = (self.solution_island.age // self.trainer_update_freq)\
                   % len(self.trainers)
        if self.verbose:
            LOGGER.debug("updating trainer at location " + str(location))
        self.trainers[location] = s_best

    def generational_step(self):
        """
        generational step for solution population, This function
        takes the necessary steps for the other populations to maintain desired
        predictor/solution computation ratio
        """
        # do some step(s) on predictor island if the ratio is low
        current_ratio = (float(self.predictor_island.fitness_evals) /
                         (self.predictor_island.fitness_evals +
                          float(self.solution_island.fitness_evals) /
                          self.predictor_to_solution_eval_cost))

        # evolving predictors
        while current_ratio < self.predictor_ratio:
            # update trainers if it is time to
            if (self.predictor_island.age+1) % self.trainer_update_freq == 0:
                self.add_new_trainer()
                for indv in self.predictor_island.pop:
                    indv.fit_set = False
            # do predictor step
            self.predictor_island.generational_step()
            if self.verbose:
                best_pred = self.predictor_island.best_indv()
                LOGGER.debug("P> " + str(self.predictor_island.age) \
                             + " " + str(best_pred.fitness) \
                             + " " + str(best_pred))
            current_ratio = (float(self.predictor_island.fitness_evals) /
                             (self.predictor_island.fitness_evals +
                              float(self.solution_island.fitness_evals) /
                              self.predictor_to_solution_eval_cost))

        # update fitness predictor if it is time to
        if (self.solution_island.age+1) % self.predictor_update_freq == 0:
            if self.verbose:
                LOGGER.debug("Updating predictor")
            self.best_predictor = self.predictor_island.best_indv().copy()
            for indv in self.solution_island.pop:
                indv.fit_set = False

        # do step on solution island
        self.solution_island.generational_step()
        self.solution_island.update_pareto_front()
        if self.verbose:
            best_sol = self.solution_island.pareto_front[0]
            LOGGER.debug("S> " + str(self.solution_island.age) \
                         + " " + str(best_sol.fitness) \
                         + " " + str(best_sol.latexstring()))

    def dump_populations(self, s_subset=None, p_subset=None, t_subset=None,
                         with_removal=False):
        """
        Dump the 3 populations to a pickleable object (tuple of lists)

        :param s_subset: list of indices for the subset of the solution
                         population which is dumped. A None value results in
                         all of the population being dumped.
        :param p_subset: list of indices for the subset of the fitness
                         predictor population which is dumped. A None value
                         results in all of the population being dumped.
        :param t_subset: list of indices for the subset of the trainer
                         population which is dumped. A None value results in
                         all of the population being dumped.
        :param with_removal: boolean describing whether the elements should be
                             removed from population after dumping
        :return: tuple of lists of populations
        """
        # dump solutions
        solution_list = self.solution_island.dump_population(s_subset,
                                                             with_removal)

        # dump predictors
        predictor_list = self.predictor_island.dump_population(p_subset,
                                                               with_removal)

        # dump trainers
        trainer_list = []
        if t_subset is None:
            t_subset = list(range(len(self.trainers)))
        for i, (indv, tfit) in enumerate(zip(self.trainers,
                                             self.trainers_true_fitness)):
            if i in t_subset:
                trainer_list.append(
                    (self.solution_island.gene_manipulator.dump(indv), tfit))
        if with_removal:
            self.trainers[:] = [indv for i, indv in enumerate(self.trainers)
                                if i not in t_subset]
            self.trainers_true_fitness[:] = \
                [tfit for i, tfit in enumerate(self.trainers_true_fitness) if
                 i not in t_subset]

        return solution_list, predictor_list, trainer_list

    def load_populations(self, pop_lists, replace=True):
        """
        load 3 populations from pickleable object

        :param pop_lists: tuple of lists of the 3 populations
        :param replace: default (True) value results in all of the population
               being loaded/replaced. False value means that the
               population in pop_list is appended to the current
               population
        """
        # load solutions
        self.solution_island.load_population(pop_lists[0], replace)

        # load predictors
        self.predictor_island.load_population(pop_lists[1], replace)

        # load trainers
        if replace:
            self.trainers = []
            self.trainers_true_fitness = []
        for indv_list, t_fit in pop_lists[2]:
            self.trainers.append(
                self.solution_island.gene_manipulator.load(indv_list))
            self.trainers_true_fitness.append(t_fit)

        self.best_predictor = self.predictor_island.best_indv().copy()

    def print_trainers(self):
        """
        For debugging: print trainers to screen
        """
        for i, train, tfit in zip(list(range(len(self.trainers))),
                                  self.trainers,
                                  self.trainers_true_fitness):
            LOGGER.debug("T> " + str(i) + " " + str(tfit) + " " + \
                         train.latexstring())

    def use_true_fitness(self):
        """
        Sets the fitness function for the solution population to the true
        (full) fitness rather than using a fitness predictor.
        """
        self.solution_island.fitness_function = \
            self.true_fitness_plus_complexity
        for indv in self.solution_island.pop:
            indv.fit_set = False

    def true_fitness_plus_complexity(self, solution):
        """
        Gets the true (full) fitness and complexity of a solution individual

        :param solution: individual of the solution population for which the
                         fitness will be calculated
        :return: fitness, complexity
        """
        return self.solution_fitness_true(solution), solution.complexity()
