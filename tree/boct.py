#!/usr/bin/env python
# coding: utf-8

from collections import namedtuple

import numpy as np
from gurobipy import *

class binOptimalDecisionTreeClassifier:
    """
    Binary Linear optimal classfication tree
    """
    def __init__(self, max_depth=3, timeLimit=600, output=True):
        self.max_depth = max_depth
        self.timeLimit = timeLimit
        self.output = output
        self.trained = False

    def fit(self, x, y):
        """
        fit training data
        """
        # solve MIP
        m, e, f, l, p, q = self._buildMIP(x, y)
        m.optimize()

        n_index = [i+1 for i in range(2 ** (self.max_depth + 1) - 1)]
        b_index = n_index[:-2**self.max_depth] # branch nodes
        l_index = n_index[-2**self.max_depth:] # leaf nodes

        # get parameters
        self._p = {ind:p[ind].x for ind in p}

        # get splition critera
        self.split = {}
        for t in b_index:
            for j in range(self.p):
                if f[t,j].x > 1e-3:
                    feature = j
            ind = 0
            for i in range(self.bin_num):
                ind = ind * 2 + int(q[t,i].x)
            self.split[t] = (feature, self.thresholds[feature][-ind])

        self.trained = True

    def predict(self, x):
        """
        model prediction
        """
        assert self.trained, 'This binOptimalDecisionTreeClassifier instance is not fitted yet.'

        # leaf nodes
        l_index = [i for i in range(2 ** self.max_depth, 2 ** (self.max_depth + 1))]

        # leaf label
        labelmap = {}
        for t in l_index:
            for k in self.labels:
                if self._p[t,k] >= 1e-2:
                    labelmap[t] = k

        y_pred = []
        for xi in x:
            t = 1
            while t not in l_index:
                j, threshold = self.split[t]
                right = (xi[j] >= threshold)
                if right:
                    t = 2 * t + 1
                else:
                    t = 2 * t
            # label
            y_pred.append(labelmap[t])

        return np.array(y_pred)

    def _buildMIP(self, x, y):
        """
        build MIP formulation for Optimal Decision Tree
        """
        # data size
        self.n, self.p = x.shape
        print('Training data include {} instances, {} features.'.format(self.n,self.p))

        # node index
        n_index = [i+1 for i in range(2 ** (self.max_depth + 1) - 1)]
        b_index = n_index[:-2**self.max_depth] # branch nodes
        l_index = n_index[-2**self.max_depth:] # leaf nodes
        # labels
        self.labels = np.unique(y)
        # thresholds
        self.thresholds = self._getThresholds(x, y)
        self.bin_num = int(np.ceil(np.log2(max([len(threshold) for threshold in self.thresholds]))))

        # create a model
        m = Model('m')

        # time limit
        m.Params.timeLimit = self.timeLimit
        # output
        m.Params.outputFlag = self.output

        # model sense
        m.modelSense = GRB.MINIMIZE

        # varibles
        e = m.addVars(l_index, self.labels, vtype=GRB.CONTINUOUS, name='e') # leaf node misclassfication
        f = m.addVars(b_index, self.p, vtype=GRB.BINARY, name='f') # splitting feature
        l = m.addVars(self.n, l_index, vtype=GRB.CONTINUOUS, name='z') # leaf node assignment
        p = m.addVars(l_index, self.labels, vtype=GRB.BINARY, name='p') # node prediction
        q = m.addVars(b_index, self.bin_num, vtype=GRB.BINARY, name='q') # threshold selection

        # objective function
        m.setObjective(e.sum())

        # constraints
        m.addConstrs(f.sum(t, '*') == 1 for t in b_index)
        m.addConstrs(l.sum(r, '*') == 1 for r in range(self.n))
        m.addConstrs(p.sum(t, '*') == 1 for t in l_index)
        for j in range(self.p):
            for b in self._getBins(0, len(self.thresholds[j])-1):
                # left
                lb, ub = self.thresholds[j][b.ur[0]], self.thresholds[j][b.ur[1]]
                M = np.sum(np.logical_and(x[:,j] >= lb, x[:,j] <= ub))
                for t in b_index:
                    expr = M * f[t,j]
                    expr += quicksum(quicksum(l[i,s]
                                              for s in self. _getLeftLeafs(t))
                                     for i in range(self.n) if lb <= x[i,j] <= ub)
                    num = 0
                    for i, ind in enumerate(b.t):
                        if ind == 0:
                            expr += M * q[t,i]
                            num = num + 1
                    expr += M * q[t,len(b.t)]
                    num = num + 1
                    m.addConstr(expr <= M + num * M)
                # right
                lb, ub = self.thresholds[j][b.lr[0]], self.thresholds[j][b.lr[1]]
                M = np.sum(np.logical_and(x[:,j] >= lb, x[:,j] <= ub))
                for t in b_index:
                    expr = M * f[t,j]
                    expr += quicksum(quicksum(l[i,s]
                                              for s in self. _getRightLeafs(t))
                                     for i in range(self.n) if lb <= x[i,j] <= ub)
                    for i, ind in enumerate(b.t):
                        if ind == 1:
                            expr -= M * q[t,i]
                    expr -= M * q[t,len(b.t)]
                    m.addConstr(expr <= M)
            # min and max
            M = np.sum(self.thresholds[j][-1] < x[:,j]) + np.sum(x[:,j] < self.thresholds[j][0])
            m.addConstrs(M * f[t,j]
                         +
                         quicksum(quicksum(l[i,s]
                                           for s in self. _getLeftLeafs(t))
                                  for i in range(self.n) if self.thresholds[j][-1] < x[i,j])
                         +
                         quicksum(quicksum(l[i,s]
                                           for s in self. _getRightLeafs(t))
                                  for i in range(self.n) if x[i,j] < self.thresholds[j][0])
                         <=
                         M
                         for t in b_index)
        for t in l_index:
            for c in self.labels:
                M = np.sum(y == c)
                l_sum = 0
                for i in range(self.n):
                    if y[i] == c:
                        l_sum += l[i,t]
                m.addConstr(l_sum - M * p[t,c] <= e[t,c])

        return m, e, f, l, p, q

    def _getThresholds(self, x, y):
        """
        obtaining all possible thresholds
        """
        thresholds = []
        for j in range(self.p):
            threshold = []
            prev_i = np.argmin(x[:,j])
            prev_label = y[prev_i]
            for i in np.argsort(x[:,j])[1:]:
                yi = y[x[:,j] == x[i,j]]
                if not np.all(prev_label == yi) and x[i,j] != x[prev_i,j]:
                    threshold.append((x[prev_i,j] + x[i,j]) / 2)
                    prev_label = y[i]
                prev_i = i
            thresholds.append(threshold)
        return thresholds

    def _getBins(self, tmin, tmax):
        """
        obtaining the binary encoding value ranges
        """
        bin_ranges = namedtuple('Bin', ['lr', 'ur', 't'])

        if tmax <= tmin:
            return []

        if tmax - tmin <= 1:
            return [bin_ranges([tmin,tmax], [tmin,tmax], [])]

        tmid = int((tmax - tmin) / 2)
        bins = [bin_ranges([tmin,tmin+tmid+1], [tmin+tmid,tmax], [])]

        for b in self._getBins(tmin, tmin+tmid):
            bins.append(bin_ranges(b.lr, b.ur, [0] + b.t))
        for b in self._getBins(tmin+tmid+1, tmax):
            bins.append(bin_ranges(b.lr, b.ur, [1] + b.t))

        return bins

    def _getLeftLeafs(self, t):
        """
        get leaves under the left branch
        """
        n_index = [i+1 for i in range(2 ** (self.max_depth + 1) - 1)]
        l_index = n_index[-2**self.max_depth:]
        tl = t * 2
        ll_index = []
        for t in l_index:
            tp = t
            while tp:
                if tp == tl:
                    ll_index.append(t)
                tp //= 2
        return ll_index

    def _getRightLeafs(self, t):
        """
        get leaves under the left branch
        """
        n_index = [i+1 for i in range(2 ** (self.max_depth + 1) - 1)]
        l_index = n_index[-2**self.max_depth:]
        tr = t * 2 + 1
        rl_index = []
        for t in l_index:
            tp = t
            while tp:
                if tp == tr:
                    rl_index.append(t)
                tp //= 2
        return rl_index
