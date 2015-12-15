from itertools import combinations
from collections import defaultdict
from scipy.stats import rv_discrete
from scipy.spatial.distance import cosine
import numpy as np
import pickle
import time
import os

import common as cmn

class Algo:
    """Abstract Algo class where is defined the basic behaviour of a recomender
    algorithm"""
    def __init__(self, rm, ur, mr, movieBased=False, withDump=True):

        # whether the algo will be based on users
        # if the algo is user based, x denotes a user and y a movie
        # if the algo is movie based, x denotes a movie and y a user
        self.ub = not movieBased 

        if self.ub:
            self.rm = rm.T # we take the transpose of the rating matrix
            self.lastXi = cmn.lastUi
            self.lastYi = cmn.lastMi
            self.xr = ur
            self.yr = mr
        else:
            self.lastXi = cmn.lastMi
            self.lastYi = cmn.lastUi
            self.rm = rm
            self.xr = mr
            self.yr = ur

        self.est = 0 # set by the estimate method of the child class

        self.withDump = withDump
        self.infos = {}
        self.infos['name'] = 'undefined'
        self.infos['params'] = {} # dict of params specific to any algo
        self.infos['params']['Based on '] = 'users' if self.ub else 'movies'
        self.infos['ub'] = self.ub
        self.infos['preds'] = [] # list of predictions. see updatePreds
        self.infos['ur'] = ur # user ratings  dict
        self.infos['mr'] = mr # movie ratings dict
        self.infos['rm'] = self.rm  # rating matrix
        # Note: there is a lot of duplicated data, the dumped file will be
        # HUGE.

    def dumpInfos(self):
        if not self.withDump:
            return
        if not os.path.exists('./dumps'):
            os.makedirs('./dumps')
        
        date = time.strftime('%y%m%d-%Hh%Mm%S', time.localtime())
        name = ('dumps/' + date + '-' + self.infos['name'] + '-' +
            str(len(self.infos['preds'])))
        pickle.dump(self.infos, open(name,'wb'))

    def getx0y0(self, u0, m0):
        """return x0 and y0 based on the self.ub variable (see constructor)"""
        if self.ub:
            return u0, m0
        else:
            return m0, u0

    def updatePreds(self, u0, m0, r0, output=True):
        """update preds list and print some info if required
        
        should be called right after the estimate method
        """

        if output:
            if self.est == 0:
                print(cmn.Col.FAIL + 'Impossible to predict' + cmn.Col.ENDC)
            if self.est == r0:
                print(cmn.Col.OKGREEN + 'OK' + cmn.Col.ENDC)
            else:
                print(cmn.Col.FAIL + 'KO ' + cmn.Col.ENDC + str(self.est))

        # a prediction is a dict with the following keys
        # 'wasImpossible' : whether or not the prediction was possible
        # 'u0', 'm0', 'r0' (true rating) and 'est' (estimated rating)
        # '3tuples' (only if algo is analogy based). A list containing all the
        # 3-tuples used for estimation (structure content may depend on the algo)
        predInfo = {}
        if self.est == 0:
            self.est = 3 # default value
            predInfo['wasImpossible'] = True
        else:
            predInfo['wasImpossible'] = False

        predInfo['u0'] = u0 ; predInfo['m0'] = m0; predInfo['r0'] = r0
        predInfo['est'] = self.est
        self.infos['preds'].append(predInfo)
    
    def cut_estimate(self, inf, sup):
        self.est = min(sup, self.est)
        self.est = max(inf, self.est)

    def iterAllRatings(self):
        for x, xRatings in self.xr.items():
            for y, r in xRatings:
                yield x, y, r

class AlgoRandom(Algo):
    """predict a random rating based on the distribution of the training set"""
    
    def __init__(self, rm, ur, mr):
        super().__init__(rm, ur, mr)
        self.infos['name'] = 'random'

        # estimation of the distribution
        fqs = [0, 0, 0, 0, 0]
        for x in range(1, self.lastXi):
            for y in range(1, self.lastYi):
                if self.rm[x, y] > 0:
                    fqs[self.rm[x, y] - 1] += 1
        fqs = [fq/sum(fqs) for fq in fqs]
        self.distrib = rv_discrete(values=([1, 2, 3, 4, 5], fqs))

    def estimate(self, *_):
        self.est = self.distrib.rvs()

class AlgoUsingSim(Algo):
    """Abstract class for algos using a similarity measure
    sim parameter can be 'Cos' or 'MSD' for mean squared difference"""
    def __init__(self, rm, ur, mr, movieBased, sim, **kwargs):
        super().__init__(rm, ur, mr, movieBased, **kwargs)

        self.infos['params']['sim'] = sim
        self.constructSimMat(sim) # we'll need the similiarities

    def constructSimMat(self, sim):
        """construct the simlarity matrix"""
        knownSim = ['cos', 'MSD', 'MSDClone']
        if not sim in knownSim:
            raise NameError('WrongSimName')

        print("computing the similarity matrix...")
        self.simMat = np.empty((self.lastXi + 1, self.lastXi + 1))
        if sim == 'cos':
            self.constructCosineSimMat()
        elif sim == 'MSD':
            self.constructMSDSimMat()
            return

    def constructCosineSimMat(self):
        """compute the cosine similarity between all pairs of xs.

        Technique inspired from MyMediaLite"""

        prods = defaultdict(int)  # sum (r_ui * r_vi) for common items
        freq = defaultdict(int)   # number common items
        sqi = defaultdict(int)  # sum (r_ui ^ 2) for common items
        sqj = defaultdict(int)  # sum (r_vi ^ 2) for common items

        for y, yRatings in self.yr.items():
            for (xi, r1), (xj, r2) in combinations(yRatings, 2):
                # note : accessing and updating elements takes a looooot of
                # time. Yet defaultdict is still faster than a numpy array...
                prods[xi, xj] += r1 * r2
                freq[xi, xj] += 1
                sqi[xi, xj] += r1**2
                sqj[xi, xj] += r2**2

        for xi in range(1, self.lastXi + 1):
            self.simMat[xi, xi] = 1
            for xj in range(xi + 1, self.lastXi + 1):
                if freq[xi, xj] == 0:
                    self.simMat[xi, xj] = 0
                else:
                    denum = np.sqrt(sqi[xi, xj] * sqj[xi, xj])
                    self.simMat[xi, xj] = prods[xi, xj] / denum

                self.simMat[xj, xi] = self.simMat[xi, xj]

    def constructMSDSimMat(self):
        """compute the mean squared difference similarity between all pairs of
        xs. MSDSim(xi, xj) = 1/MSD(xi, xj). if MSD(xi, xj) == 0, then
        MSDSim(xi, xj) = number of common ys. Implicitely, if there are no
        common ys, sim will be zero

        Technique inspired from MyMediaLite"""

        sqDiff = defaultdict(int)  # sum (r_ui - r_vi)**2 for common items
        freq = defaultdict(int)   # number common items

        for y, yRatings in self.yr.items():
            for (xi, r1), (xj, r2) in combinations(yRatings, 2):
                # note : accessing and updating elements takes a looooot of
                # time. Yet defaultdict is still faster than a numpya array...
                sqDiff[xi, xj] += (r1 - r2)**2
                freq[xi, xj] += 1

        for xi in range(1, self.lastXi + 1):
            self.simMat[xi, xi] = 100 # completely arbitrary and useless anyway
            for xj in range(xi, self.lastXi + 1):
                if sqDiff[xi, xj] == 0:  # return number of common ys
                    self.simMat[xi, xj] = freq[xi, xj]
                else:  # return inverse of MSD
                    self.simMat[xi, xj] = freq[xi, xj] / sqDiff[xi, xj]

                self.simMat[xj, xi] = self.simMat[xi, xj]

    def simMSDClone(self, xi, xj):
        """ return the similarity between two users or movies using Mean
        Squared Difference with Clone"""

        # movies rated by xi andxj or users having rated xi and xj
        Yij = [y for (y, _) in self.xr[xi] if self.rm[xj, y] > 0]

        if not Yij:
            return 0

        print(xi, xj)
        meanDiff = np.mean([self.rm[xi, y] - self.rm[xj, y] for y in Yij])
        # sum of squared differences:
        ssd = sum((self.rm[xi, y] - self.rm[xj, y] - meanDiff)**2 for y in Yij)
        if ssd == 0:
            return  len(Yij) # maybe we should return more ?
        return len(Yij) / ssd


class AlgoBasicCollaborative(AlgoUsingSim):
    """Basic collaborative filtering algorithm"""

    def __init__(self, rm, ur, mr, movieBased=False, sim='Cos'):
        super().__init__(rm, ur, mr, movieBased=movieBased, sim=sim)

        self.k = 40

        self.infos['name'] = 'basicCollaborative'
        self.infos['params']['similarity measure'] = 'cosine'
        self.infos['params']['k'] = self.k

    def estimate(self, u0, m0):
        x0, y0 = self.getx0y0(u0, m0)
        # list of (x, sim(x0, x)) for u having rated m0 or for m rated by x0
        simX0 = [(x, self.simMat[x0, x]) for x in range(1, self.lastXi + 1) if
            self.rm[x, y0] > 0]

        # if there is nobody on which predict the rating...
        if not simX0:
            self.est = 0
            return

        # sort simX0 by similarity
        simX0 = sorted(simX0, key=lambda x:x[1], reverse=True)

        # let the KNN vote
        simNeighboors = [sim for (_, sim) in simX0[:self.k]]
        ratNeighboors = [self.rm[x, y0] for (x, _) in simX0[:self.k]]
        try:
            self.est = np.average(ratNeighboors, weights=simNeighboors)
        except ZeroDivisionError:
            self.est = 0

class AlgoWithBaseline(Algo):
    """Abstract class for algos that need a baseline"""
    def __init__(self, rm, ur, mr, movieBased, method, **kwargs):
        super().__init__(rm, ur, mr, movieBased, **kwargs)

        #compute users and items biases
        # see from 5.2.1 of RS handbook

        # mean of all ratings from training set
        self.mu = np.mean([r for l in self.rm for r in l if r > 0])

        self.xBiases = np.zeros(self.lastXi + 1)
        self.yBiases = np.zeros(self.lastYi + 1)

        print('Estimating biases...')
        if method == 'sgd':
            self.optimize_sgd()
        elif method == 'als':
            self.optimize_als()

    def optimize_sgd(self):
        """optimize biases using sgd"""
        lambda4 = 0.02
        gamma = 0.005
        nIter = 20
        for dummy in range(nIter):
            for x, y, r in self.iterAllRatings():
                """
            for x, xRatings in self.xr.items():
                for y, r in xRatings:
                    """
                err = r - (self.mu + self.xBiases[x] + self.yBiases[y])
                # update xBiases 
                self.xBiases[x] += gamma * (err - lambda4 *
                    self.xBiases[x])
                # udapte yBiases
                self.yBiases[y] += gamma * (err - lambda4 *
                    self.yBiases[y])

    def optimize_als(self):
        """alternatively optimize yBiases and xBiases. Probably not really an
        als"""
        reg_u = 15 
        reg_i = 10 
        nIter = 10

        self.reg_x = reg_u if self.ub else reg_i
        self.reg_y = reg_u if not self.ub else reg_i

        for dummy in range(nIter):
            self.yBiases = np.zeros(self.lastYi + 1)
            for y in range(1, self.lastYi + 1):
                devY = sum(r - self.mu - self.xBiases[x] for (x, r) in self.yr[y])
                self.yBiases[y] = devY / (self.reg_y + len(self.yr[y]))

            self.xBiases = np.zeros(self.lastXi + 1)
            for x in range(1, self.lastXi + 1):
                devX = sum(r - self.mu - self.yBiases[y] for (y, r) in self.xr[x])
                self.xBiases[x] = devX / (self.reg_x + len(self.xr[x]))
        


    def getBaseline(self, x, y):
        return self.mu + self.xBiases[x] + self.yBiases[y]


class AlgoBaselineOnly(AlgoWithBaseline):
    """ Algo using only baseline""" 

    def __init__(self, rm, ur, mr, movieBased=False, method='opt'):
        super().__init__(rm, ur, mr, movieBased, method=method)
        self.infos['name'] = 'algoBaselineOnly'

    def estimate(self, u0, m0):
        x0, y0 = self.getx0y0(u0, m0)
        self.est = self.getBaseline(x0, y0)

class AlgoClone(Algo):
    """Basic collaborative taking into accounts constant differences between
    ratings"""

    def __init__(self, rm, ur, mr, movieBased=False):
        super().__init__(rm, ur, mr, movieBased=movieBased)

        self.infos['name'] = 'clone'

    def isClone(self, xa, xb, k):
        w = [xai - xbi for (xai, xbi) in zip(xa, xb)]
        sigma = sum(abs(wi - k) for wi in w)
        return sigma <= len(w)

    def estimate(self, u0, m0):
        x0, y0 = self.getx0y0(u0, m0)

        candidates = []
        for (x, rx) in self.yr[y0]: # for ALL users that have rated y0
            # find common ratings between x0 and x
            commonRatings = [(self.rm[x0, y], self.rm[x, y]) for (y, _) in self.xr[x0] if self.rm[x, y] > 0]
            if not commonRatings: continue 
            ra, rb = zip(*commonRatings)
            for k in range(-4, 5):
                if self.isClone(ra, rb, k):
                    candidates.append(rx + k)

        if candidates:
            self.est = np.mean(candidates)
        else:
            self.est = 0

class AlgoMeanDiff(Algo):
    """Basic collaborative taking into accuonts constant differences between
    ratings"""

    def __init__(self, rm, ur, mr, movieBased=False):
        super().__init__(rm, ur, mr, movieBased=movieBased)

        self.infos['name'] = 'meanDiff'

    def meanDiff(self, ra, rb):
        """Return the mean difference between two sets or ratings and the
        weight associated to it"""

        diffs = [(rai - rbi) for (rai, rbi) in zip(ra, rb)]
        md = np.mean(diffs) # mean diff
        w = 1./(np.std(diffs) + 1) # weight
        #w = 100 - np.std(diffs) # weight
        return md, w


    def estimate(self, u0, m0):
        x0, y0 = self.getx0y0(u0, m0)

        candidates = []
        weights = []
        for (x, rx) in self.yr[y0]: # for ALL users that have rated y0

            # find common ratings between x0 and x
            commonRatings = [(self.rm[x0, y], self.rm[x, y]) for (y, _) in self.xr[x0] if self.rm[x, y] > 0]
            if not commonRatings: continue 
            ra, rb = zip(*commonRatings)

            # compute the mean diff between x0 and x, and attribute a weight
            # to x
            md, w = self.meanDiff(ra, rb)
            candidates.append(rx + md)
            weights.append(w)
					
        if candidates:
            self.est = np.average(candidates, weights=weights)
        else:
            self.est = 0

class AlgoCollabMeanDiff(AlgoUsingSim):
    """Basic collaborative taking into accuonts constant differences between
    ratings"""

    def __init__(self, rm, ur, mr, movieBased=False, sim='MSDClone'):
        super().__init__(rm, ur, mr, movieBased=movieBased, sim=sim)

        self.infos['name'] = 'CollabMeanDiff'

        self.k = 40

        self.infos['params']['similarity measure'] = sim
        self.infos['params']['k'] = self.k

    def meanDiff(self, xa, xb):
        """Return the mean difference between two users """
        commonRatings = [(self.rm[xa, y], self.rm[xb, y]) for (y, _) in self.xr[xa] if self.rm[xb, y] > 0]
        if not commonRatings: return 0
        ra, rb = zip(*commonRatings)

        diffs = [(rai - rbi) for (rai, rbi) in zip(ra, rb)]
        md = np.mean(diffs) # mean diff

        return md

    def estimate(self, u0, m0):
        x0, y0 = self.getx0y0(u0, m0)
        # list of (x, sim(x0, x)) for u having rated m0 or for m rated by x0
        simX0 = [(x, self.simMat[x0, x]) for x in range(1, self.lastXi + 1) if
            self.rm[x, y0] > 0]

        # if there is nobody on which predict the rating...
        if not simX0:
            self.est = 0
            return

        # sort simX0 by similarity
        simX0 = sorted(simX0, key=lambda x:x[1], reverse=True)

        # let the KNN vote
        simNeighboors = [sim for (_, sim) in simX0[:self.k]]
        ratNeighboors = [self.rm[x, y0] + self.meanDiff(x0, x) for (x, _) in simX0[:self.k]]
        try:
            self.est = np.average(ratNeighboors, weights=simNeighboors)
        except ZeroDivisionError:
            self.est = 0