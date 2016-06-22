# -*- coding: utf-8 -*-

from __future__ import print_function
import sys
import os
import os.path as op
import collections
import re
import itertools as it
from collections import OrderedDict
import networkx as nx
import numpy as np
from heapq import *
import random

REQUIRED = ['family_id', 'sample_id', 'paternal_id',
            'maternal_id', 'sex', 'phenotype']

try:
    import matplotlib
    matplotlib.use("Agg")
except ImportError:
    # dont have mpl installed.
    pass

def get_s(*args):
    s = 1.0 + np.nansum(args, axis=0)
    s **= 2.5
    s /= s.mean()
    s *= 18.0
    return s

#https://gist.githubusercontent.com/kachayev/5956408/raw/c918417ef7f3c0deb6a0a1223a49035dcca84077/uf.py
class UF(object):
    __slots__ = ('p', 'rank')

    def __init__(self, size):
        self.p = [None]*size
        self.rank = [1]*size

    def make(self, el):
        self.p[el] = el

    def find(self, el):
        if self.p[el] == el: return el
        self.p[el] = self.find(self.p[el])
        return self.p[el]

    def unite(self, l, r):
        li, ri = self.find(l), self.find(r)
        if self.rank[li] < self.rank[ri]:
            self.p[li] = ri
        else:
            self.p[ri] = li
            if self.rank[li] == self.rank[ri]:
                self.rank[li] += 1


# https://github.com/tmr232/Sark/blob/1b1d9a50c23e7a0774a9849137dc80998b1e9c46/sark/graph.py
def lowest_common_ancestors(G, targets):
    common_ancestors = None
    all_ancestors = set()
    for target in targets:
        parents = set()
        q = collections.deque()
        q.append(target)

        while q:
            n = q.popleft()
            if n in parents:
                continue
            for p in G.successors_iter(n):
                q.append(p)
            parents.add(n)

        all_ancestors.update(parents)

        if common_ancestors is None:
            common_ancestors = parents
        else:
            common_ancestors &= parents

    lowest_common = set()
    if common_ancestors is not None:
        for p in common_ancestors:
            if any(child not in common_ancestors and child in all_ancestors for child in G.predecessors_iter(p)):
                lowest_common.add(p)

    return lowest_common

if sys.version_info[0] == 3:
    basestring = str

class UNKNOWN(object):
    def __str__(self):
        return "-9"

class PHENOTYPE(object):
    AFFECTED = True
    UNAFFECTED = False
    UNKNOWN = UNKNOWN()

    @classmethod
    def lookup(cls, i):
        return {'2': cls.AFFECTED, '1': cls.UNAFFECTED}.get(i, cls.UNKNOWN)

    @classmethod
    def rlookup(cls, i):
        return {cls.AFFECTED: 'affected', cls.UNAFFECTED: 'unaffected'}.get(i, cls.UNKNOWN)


class SEX(object):
    MALE = 'male'
    FEMALE = 'female'
    UNKNOWN = UNKNOWN()

    @classmethod
    def lookup(cls, i):
        return {'1': cls.MALE, '2': cls.FEMALE}.get(i, cls.UNKNOWN)

    @classmethod
    def rlookup(cls, i):
        return {cls.MALE: 'male', cls.FEMALE: 'female'}.get(i, cls.UNKNOWN)

UNKNOWN = UNKNOWN()


class Sample(object):

    def __init__(self, family_id, sample_id, paternal_id, maternal_id, sex,
                 phenotype, extra_attrs=None, header=None,
                 missing=('-9', '0', '.'), warn=True):
        self.warn = warn
        self.family_id = family_id
        self.sample_id = sample_id
        self.dad = None
        self.mom = None
        self.paternal_id = UNKNOWN if paternal_id in missing else paternal_id
        self.maternal_id = UNKNOWN if maternal_id in missing else maternal_id
        if self.paternal_id != UNKNOWN:
            self.dad = self.paternal_id
        if self.maternal_id != UNKNOWN:
            self.mom = self.maternal_id
        self._sex = sex
        self.phenotype = phenotype
        self.sex = SEX.lookup(sex)
        self.affected = PHENOTYPE.lookup(phenotype)
        self.kids = []
        self.header = header or REQUIRED
        self.header[:6] = REQUIRED
        self.attrs = extra_attrs or []

    def dict(self):
        d = OrderedDict((k, getattr(self, k)) for k in self.header)
        for k in ('maternal_id', 'paternal_id', 'sex'):
            d[k] = str(d[k])
        d['phenotype'] = 'affected' if self.affected else 'unaffected'
        return d

    def __eq__(self, other):
        if self is None or other is None:
            return False
        if isinstance(other, basestring):
            return self.sample_id == other
        return (self.sample_id == other.sample_id) and (self.family_id ==
                                                        other.family_id)
    def __hash__(self):
        return hash((self.sample_id, self.family_id))

    def _get_mom(self):
        return self._mom

    def _set_mom(self, mom):
        if isinstance(mom, Sample):
            if mom.sex == SEX.MALE:
                if self.warn:
                    sys.stderr.write("pedigree warning: '%s' is mom but has male sex\n" % mom.sample_id)
            elif mom.sex == SEX.UNKNOWN:
                if self.warn:
                    sys.stderr.write("pedigree notice: '%s' is mom but has unknown sex. Setting to female\n" % mom.sample_id)

            if mom.family_id != self.family_id:
                if self.warn:
                    sys.stderr.write("pedigree warning: '%s' is mom has different family_id from %s\n" % (mom.sample_id, self.sample_id))

            if mom.sample_id == self.sample_id:
                if self.warn:
                    sys.stderr.write("pedigree warning: '%s' is mom of self\n" % (self.sample_id))

        self._mom = mom

    mom = property(_get_mom, _set_mom)

    def _get_dad(self):
        return self._dad

    def _set_dad(self, dad):
        if isinstance(dad, Sample):
            if dad.sex == SEX.FEMALE:
                if self.warn:
                    sys.stderr.write("pedigree warning: '%s' is dad but has female sex\n" % dad.sample_id)
            elif dad.sex == SEX.UNKNOWN:
                if self.warn:
                    sys.stderr.write("pedigree notice: '%s' is dad but has unknown sex. Setting to male\n" % dad.sample_id)

            if dad.family_id != self.family_id:
                if self.warn:
                    sys.stderr.write("pedigree warning: '%s' is dad has different family_id from %s\n" % (dad.sample_id, self.sample_id))

            if dad.sample_id == self.sample_id:
                if self.warn:
                    sys.stderr.write("pedigree warning: '%s' is dad of self\n" % (self.sample_id))

        self._dad = dad

    dad = property(_get_dad, _set_dad)

    def __repr__(self):
        v = "%s('%s', '%s', '%s', '%s', '%s', '%s'" % (self.__class__.__name__,
                                                       self.family_id,
                                                       self.sample_id,
                                                       self.paternal_id,
                                                       self.maternal_id,
                                                       SEX.rlookup(self.sex),
                                                       PHENOTYPE.rlookup(self.affected))
        if self.attrs:
            v += ", " + str(self.attrs)
        v += ")"
        return v

    def __getattr__(self, key):
        if not key in self.header:
            raise AttributeError(key)
        try:
            return self.attrs[self.header.index(key) - 6]
        except:
            raise KeyError(key)


    @property
    def siblings(self):
        sibs = []
        for parent in (self.mom, self.dad):
            if parent is UNKNOWN: continue
            sibs.extend(x for x in parent.kids if x not in sibs and x != self)
        return sibs

    @property
    def full_siblings(self):
        sibs = []

        if self.mom is None or self.dad is None:
            return sibs
        return [s for s in self.mom.kids if s in self.dad.kids and s != self]

    @classmethod
    def from_row(cls, row, header=None, warn=True):
        if isinstance(row, basestring):
            sep = "\t" if row.count("\t") > row.count(" ") else " "
            if sep == " ":
                row = [x.strip() for x in re.split("\s+", row.strip("\n"))]
            else:
                row = [x.strip() for x in row.strip("\n").split(sep)]
        return cls(row[0], row[1], row[2] or "-9", row[3] or "-9", row[4], row[5],
                   row[6:] if len(row) > 6 else None, header=header, warn=warn)

    def __str__(self):
        v = "%s %s %s %s %s %s" % (self.family_id, self.sample_id,
                                   self.paternal_id,
                                   self.maternal_id,
                                   self._sex, self.phenotype)
        if self.attrs:
            v += " " + " ".join(self.attrs)
        return v


class Family(object):
    """Family groups samples in the same family.
    A new object is created with a list of `Sample` objects with
    the same `family_id`.
    Iterating over the family gives the samples in the order they were given to
    the constructor.
    """
    def __init__(self, samples, warn=True):
        assert len(set(s.family_id for s in samples)) == 1
        self.unknown_samples = []
        self.samples = samples
        self.warn = warn
        self._build()
        for u in self.unknown_samples:
            if self.warn:
                print("unknown sample: %s in family: %s" % (u,
                      samples[0].family_id), file=sys.stderr)

    def __iter__(self):
        self._index = 0
        return self

    def next(self):
        try:
            sample = self.samples[self._index]
        except IndexError:
            raise StopIteration
        self._index += 1
        return sample

    __next__ = next

    def summary(self):
        affection = {PHENOTYPE.AFFECTED: 0, PHENOTYPE.UNAFFECTED: 0,
                     PHENOTYPE.UNKNOWN: 0}
        sex = {SEX.MALE: 0, SEX.FEMALE: 0, SEX.UNKNOWN: 0}

        trios, quads = 0, 0

        for s in self.samples:
            affection[s.affected] += 1
            sex[s.sex] += 1
            if s.mom and s.dad and s.affected:
                trios += 1
            if s.affected and list(s.full_siblings):
                quads += 1
        return affection, sex, trios, quads

    @property
    def sib_pairs(self):
        "yield pairs of siblings."
        seen = set()
        for s in self.samples:
            sibs = list(s.full_siblings)
            for sib in sibs:
                if (s.sample_id, sib.sample_id) in seen: continue
                if (sib.sample_id, s.sample_id) in seen: continue
                seen.add((s.sample_id, sib.sample_id))
                yield s, sib

    @property
    def parent_child(self):
        "yield child, parent pairs"
        seen = set()
        for s in self.samples:
            for parent in (p for p in [s.mom, s.dad] if p is not None):
                if (s.sample_id, parent.sample_id) in seen: continue
                if (parent.sample_id, s.sample_id) in seen: continue
                seen.add((s.sample_id, parent.sample_id))
                yield s, parent

    def _build(self):
        by_id = OrderedDict()
        for s in self.samples:
            by_id[s.sample_id] = s
        by_id[None] = None
        for s in self.samples:
            if s.paternal_id != UNKNOWN:
                try:
                    s.dad = by_id[s.paternal_id]
                    s.dad.kids.append(s)
                except KeyError:
                    s.dad = s.paternal_id
                    self.unknown_samples.append(s.paternal_id)
            if s.maternal_id != UNKNOWN:
                try:
                    s.mom = by_id[s.maternal_id]
                    s.mom.kids.append(s)
                except KeyError:
                    s.mom = s.maternal_id
                    self.unknown_samples.append(s.maternal_id)

    @property
    def affecteds(self):
        "generate all the affecteds in a family"
        for s in self.samples:
            if s.affected:
                yield s

    @property
    def unaffecteds(self):
        "generate all the unaffecteds in a family"
        for s in self.samples:
            if s.affected is False:
                yield s

    def trios(self, affected=True):
        "generate all the trios in a family"
        for s in self.samples:
            if affected is not None:
                if affected != s.affected:
                    continue
            if s.mom and s.dad:
                yield (s, s.mom, s.dad)


class Ped(object):
    """Manipulate pedigree data

    >>> p = Ped('peddy/tests/a.ped')
    >>> p
    Ped('peddy/tests/a.ped')

    >>> s = next(p.samples())
    >>> s
    Sample('family_1', 'child_1', 'dad_1', 'mom_1', 'male', 'affected', ['caucasian'])
    >>> s.ethnicity
    'caucasian'

    >>> next(p.samples(phenotype=PHENOTYPE.UNAFFECTED))
    Sample('family_1', 'dad_1', '-9', '-9', 'male', 'unaffected', ['caucasian'])

    >>> next(p.samples(phenotype=PHENOTYPE.UNAFFECTED, sex=SEX.FEMALE))
    Sample('family_1', 'mom_1', '-9', '-9', 'female', 'unaffected', ['caucasian'])

    >>> [x.sample_id for x in p.samples(phenotype=PHENOTYPE.AFFECTED, sex=SEX.FEMALE)]
    ['kid_4', 'kid_4.1']

    #>>> p.summary()

    """

    def __init__(self, ped, warn=True):
        if isinstance(ped, basestring):
            self.filename = ped
            ped = open(ped)
        else:
            self.filename = ""
        self.warn = warn
        self._parse(ped)
        self._graph = None

    def _parse(self, fh):
        self.header = None
        families = OrderedDict()

        for i, l in enumerate(l.rstrip('\r\n') for l in fh if l.strip()):
            sep = "\t" if l.count("\t") > l.count(" ") else " "
            if sep == " ":
                toks = [x.strip() for x in re.split("\s+", l.strip("\n"))]
            else:
                toks = l.split(sep)
            if i == 0 and (toks[0][0] == "#" or toks[0].lower() in ("family_id", "kindred_id")):
                if toks[0][0] == "#":
                    toks[0] = toks[0][1:]
                self.header = toks
                continue
            sample = Sample.from_row(toks, header=self.header, warn=self.warn)
            if not sample.family_id in families:
                families[sample.family_id] = []

            families[sample.family_id].append(sample)

        self.families = OrderedDict()

        for family_id, samples in families.items():
            self.families[family_id] = Family(samples, warn=self.warn)

    def __getitem__(self, sample_id):
        sample = [s for s in self.samples() if s.sample_id == sample_id]
        if len(sample) == 0:
            raise KeyError("%s not found" % sample_id)
        elif len(sample) > 1:
            raise Exception("multiple samples with id %s found" % sample_id)
        return sample[0]

    def samples(self, phenotype=None, sex=None, **kwargs):

        if phenotype is None:
            samps = (x for fam in self.families.values() for x in fam)
        else:
            samps = (x for fam in self.families.values() for x in fam if x.affected == phenotype)

        if sex is not None:
            samps = [x for x in samps if x.sex == sex]

        for k, v in kwargs.items():
            samps = [x for x in samps if getattr(x, k) == v]

        return iter(samps)

    def __repr__(self):
        return "%s('%s')" % (self.__class__.__name__, self.filename)

    def to_json(self, samples=None):
        import json
        if samples is None:
            dicts = [s.dict() for s in self.samples()]
        else:
            dicts = [s.dict() for s in self.samples() if s.sample_id in set(samples)]
        return json.dumps(dicts)

    def relation(self, sample_a, sample_b):
        if isinstance(sample_a, basestring):
            a = self.get(sample_a)
            if isinstance(a, list):
                a = a[0]
        else:
            a = sample_a
        if isinstance(sample_b, basestring):
            b = self.get(sample_b)
            if isinstance(b, list):
                b = b[0]
        else:
            b = sample_b

        if a is None or b is None:
            return 'unknown'

        # TODO: should we check anyway or just bail early like this
        if a.family_id != b.family_id:
            return 'unrelated'

        if set(a.kids).intersection(b.kids):
            return "mom-dad"

        if a.mom == b or b.mom == a or a.dad == b or b.dad == a:
            return 'parent-child'

        # TODO: do BFS
        if a.mom is None and a.dad is None and b.mom is None and b.dad is None:
            return 'unrelated'

        if a.mom == b.mom and a.dad == b.dad and None not in (a.mom, a.dad):
            return 'full siblings'

        if (a.mom is not None and a.mom == b.mom) or (a.dad is not None and a.dad == b.dad):
            return 'siblings'

        else:
            return 'related level 2'

    def get(self, sample_id, family_id=None, cache={}):
        """
        get takes a sample id and optional family_id and returns the object(s)
        associated with it.
        """
        if (sample_id, family_id) in cache:
            return cache[(sample_id, family_id)]
        a = [x for x in self.samples() if x.sample_id == sample_id]
        if len(a) > 1 and family_id is None:
            print("multiple samples found in ped file for %s" % sample_id, file=sys.stderr)

        if family_id is not None:
            a = [x for x in a if x.family_id == family_id]
        if len(a) > 1:
            print("multiple samples found in ped file for %s" % sample_id, file=sys.stderr)
        elif len(a) == 0:
            print("no sample found in ped file for %s" % sample_id, file=sys.stderr)
            return None
        elif len(a) == 1:
            a = a[0]
        cache[(sample_id, family_id)] = a
        return a

    def _setup_graph(self):
        gr = self._graph = nx.DiGraph()
        for s in self.samples():
            if s.mom is not None:
                if isinstance(s.mom, basestring):
                    gr.add_edge(s.sample_id, s.mom)
                elif s.mom != UNKNOWN:
                    gr.add_edge(s.sample_id, s.mom.sample_id)
            if s.dad is not None:
                if isinstance(s.dad, basestring):
                    gr.add_edge(s.sample_id, s.dad)
                elif s.dad != UNKNOWN:
                    gr.add_edge(s.sample_id, s.dad.sample_id)
            #if s.dad is None and s.mom is None:
                # shoudl top-node be s.family_id?
            #    gr.add_edge(s.sample_id, None)

    def relatedness_coefficient(self, sample_a, sample_b, _empty=set([None])):
        """Coefficient of relatedness between 2 samples."""
        if isinstance(sample_a, Sample):
            sample_a = sample_a.sample_id
        if isinstance(sample_b, Sample):
            sample_b = sample_b.sample_id

        if sample_a == sample_b: return 1.0
        if self._graph is None:
            self._setup_graph()
        if not (sample_a in self._graph and sample_b in self._graph):
            return -1.0
        lca = lowest_common_ancestors(self._graph, [sample_a, sample_b]) - _empty
        if len(lca) == 0:
            return 0.0

        a_paths, b_paths = [], []
        for anc in lca:
            b = list(nx.all_shortest_paths(self._graph, sample_b, anc))
            if len(b) > 0 and len(b[-1]) > 0 and b[-1][0] == sample_b:
                b[-1] = b[-1][1:]
                if b[-1] == []:
                    b = b[:-1]
            if b:
                b_paths.extend(b)

            a = list(nx.all_shortest_paths(self._graph, sample_a, anc))
            if len(a) > 0 and len(a[-1]) > 0 and a[-1][0] == sample_a:
                a[-1] = a[-1][1:]
                if a[-1] == []:
                    a = a[:-1]
            if a:
                a_paths.extend(a)

        n = 0
        if a_paths:
            a_paths = sorted(a_paths, key=len, reverse=True)[0]
            n += 1
        if b_paths:
            b_paths = sorted(b_paths, key=len, reverse=True)[0]
            n += 1
        path = a_paths + b_paths
        return n * 2.0**-len(path)

    def sex_check(self, vcf_path, min_depth=7,
                  skip_missing=True,
                  plot=False,
                  cutoff=0.6,
                  n_sites=100000,
                  pars=('X:10000-2781479', 'X:155701382-156030895')):
        """
        Check that the sex reported in the ped file matches that inferred
        using the genotypes in `vcf_path` using the ratio of HET / (HOM_REF +
        HOM_ALT)

        :param vcf str:  path to vcf
        :param min_depth int: minimum depth of variants to consider (in at least 50% of samples).
        :param n_sites int: stop after sampling this many sites in the X chromosome.
        :param skip_missing bool: don't consider samples that are not in the ped file
        :param plot bool: render a plot of the distributions by sex.
        :param pars tuple(str): pseudo autosmal regions

        :return: pandas.DataFrame
        """
        from cyvcf2 import VCF
        import numpy as np
        import pandas as pd


        vcf = VCF(vcf_path, gts012=True, lazy=False,
                  samples=[s.sample_id for s in self.samples()])

        pars = [x.split(':') for x in pars]
        pars = [(x[0], map(int, x[1].split('-'))) for x in pars]

        chrom = pars[0][0]

        hom_ref = np.zeros(len(vcf.samples), dtype=int)
        het     = np.zeros(len(vcf.samples), dtype=int)
        hom_alt = np.zeros(len(vcf.samples), dtype=int)
        kept, skipped = 0, 0
        for variant in vcf(chrom):
            # skip multi-nucleotide
            if len(variant.REF) > 1: continue
            # skip multiple alternates
            if len(variant.ALT) > 1: continue
            if variant.call_rate < 0.5: continue
            if variant.aaf < 0.01: continue
            if any(s <= variant.start and e >= variant.start for chrom, (s, e) in pars):
                skipped += 1
                continue
            depth_filter = variant.gt_depths >= min_depth
            gt_types = variant.gt_types

            hom_ref += (gt_types == 0) & depth_filter
            hom_alt += (gt_types == 2) & depth_filter
            het += (gt_types == 1) & depth_filter
            kept += 1
            if kept >= n_sites: break

        # this should be high for females and low for males
        het_ratio = het.astype(float) / (hom_alt)
        print("sex-check: %s skipped / %d kept" % (skipped, kept), file=sys.stderr)

        plot_vals = {'male': [], 'female': [], 'male_errors': [],
                    'unknown': [], 'unknown_errors': [], 'unknown_samples': [],
                    'female_errors': [], 'male_samples': [], 'female_samples':[]}
        res = []
        for i, s in enumerate(vcf.samples):
            try:
                ped_sex = str(self[s].sex)
            except KeyError:
                if skip_missing:
                    print(s)
                    continue
                ped_sex = "NA"
            val = -0.06 if np.isnan(het_ratio[i]) else het_ratio[i]
            predicted_sex = "UNKNOWN" if val < 0 else SEX.MALE if val < cutoff else SEX.FEMALE
            error = predicted_sex != ped_sex
            if ped_sex in ("NA", "-9"):
                ped_sex = "unknown"
            try:
                plot_vals[ped_sex].append(val)
            except KeyError:
                print(s, ped_sex, ped_sex.strip() == "-9")
                # sex unknown
                raise

            plot_vals[ped_sex + '_errors'].append(error)
            plot_vals[ped_sex + '_samples'].append(s)

            res.append(dict(sample_id=s, ped_sex=ped_sex, hom_ref_count=hom_ref[i],
                       het_count=het[i], hom_alt_count=hom_alt[i],
                       het_ratio=val, predicted_sex=predicted_sex,
                       error=error))

        if not plot:
            return pd.DataFrame(res)

        s = get_s(hom_ref, het, hom_alt)

        from matplotlib import pyplot as plt
        plt.close()
        import seaborn as sns
        colors = sns.color_palette('Set1', 3)

        def update_colors(colors, vals, bad_color=colors[2]):
            colors = colors[:]
            for i, v in enumerate(vals):
                if v < 0:
                    colors[i] = bad_color
            return colors

        fcolors = [colors[1] if e else colors[0] for e in plot_vals['female_errors']]
        female_xs = (np.random.uniform(size=len(plot_vals['female'])) - 0.5) / 2.1
        plt.scatter(female_xs, plot_vals['female'],
                    c=fcolors,
                    s=s,
                    edgecolors=update_colors(fcolors, plot_vals['female']),
                    marker='o')

        mcolors = [colors[0] if e else colors[1] for e in plot_vals['male_errors']]
        male_xs = (np.random.uniform(size=len(plot_vals['male'])) - 0.5) / 2.1 + 1.0
        plt.scatter(male_xs, plot_vals['male'],
                    c=mcolors,
                    s=s,
                    edgecolors=update_colors(mcolors, plot_vals['male']),
                    marker='o')

        for i, e in enumerate(plot_vals['female_errors']):
            if not e: continue
            plt.text(female_xs[i], plot_vals['female'][i], plot_vals['female_samples'][i],
                     color=colors[1], fontsize=7)

        for i, e in enumerate(plot_vals['male_errors']):
            if not e: continue
            plt.text(male_xs[i], plot_vals['male'][i], plot_vals['male_samples'][i],
                     color=colors[0], fontsize=7)

        import matplotlib.patches as mpatches
        c0 = mpatches.Patch(color=colors[0], label="female")
        c1 = mpatches.Patch(color=colors[1], label="male")

        plt.xticks([0, 1], ['female', 'male'])
        plt.xlim(-0.27, 1.27)
        plt.ylim(ymin=-0.08)
        plt.axhline(y=cutoff, color='0.75')
        plt.xlabel('Sex From Ped')
        plt.ylabel('HET / HOM_ALT [higher is more likely female]')
        plt.legend(handles=[c0, c1], title="Sex predicted\nfrom genotypes",
                   loc='upper center')
        plt.savefig(plot)
        plt.close()
        return pd.DataFrame(res)

    def het_check(self, vcf_path, plot=False, ncpus=1, min_depth=8,
                  sites=op.join(op.dirname(__file__), '1kg.sites'),
                  **kwargs):
        """
        kwargs is not used, but added here to allow same args as ped_check
        """
        import cyvcf2
        import numpy as np
        if ncpus > 16:
            ncpus = 16

        samps = [x.sample_id for x in self.samples()]
        vcf = cyvcf2.VCF(vcf_path, gts012=True, samples=samps)
        if sorted(vcf.samples) != sorted(samps):
            print("warning: sample overlap issues\n\tin vcf, not in ped: %s\n\tin ped, not in vcf: %s" % (
                  ",".join(set(vcf.samples) - set(samps)),
                  ",".join(set(samps) - set(vcf.samples))), file=sys.stderr)
        if set(vcf.samples) - set(samps) == set(vcf.samples):
            raise Exception("error: no samples from VCF found in ped")

        samps = vcf.samples
        sample_ranges, sites, gt_types = cyvcf2.par_het(vcf_path, samps, ncpus,
                sites, min_depth=min_depth)

        from .pca import pca
        if plot:
            pca_plot = plot.replace('het_', 'pca_').replace('het-', 'pca-')
            if pca_plot == plot:
                pca_plot, ext = pca_plot.rsplit(".", 1)
                pca_plot = "%s.%s%s" % (pca_plot, "pca.", ext)
        else:
            pca_plot = False
        pca_df, background_pca_df = pca(pca_plot, gt_types, sites)

        # not find outliers.
        depth = np.array([v['median_depth'] for v in sample_ranges.values()])
        #ranges = np.array([d['range'] for d in sample_ranges.values()])
        ratios = np.array([d['het_ratio'] for d in sample_ranges.values()])
        ratios_outlier = ((ratios < 0.305) | (ratios > 0.41))
        #ranges_outlier = ((ranges < 0.08) | (ranges > 0.31))

        bot = depth.mean() - 2 * depth.std()
        # remove outliers and re-calc.
        bot = depth[depth > bot].mean() - 2 * depth[depth > bot].std()
        # care less if we have really high samples so make it 5.
        top = depth.mean() + 5 * depth.std()

        depth_outlier = ((depth < bot) | (depth > top))

        for k, v in sample_ranges.items():
            v['sample_id'] = k


        for d, depth_o, ratio_o in zip(sample_ranges.values(), depth_outlier,
                                       ratios_outlier):
            d['ratio_outlier'] = ratio_o
            d['depth_outlier'] = depth_o
            d['iqr_baf'] = d.pop('range')

        import pandas as pd
        df = pd.DataFrame(sample_ranges.values())
        cols = ['sample_id'] + sorted([x for x in df.columns if x != 'sample_id'])
        df = df[cols]

        df.index = df['sample_id']

        if pca_df is not None:
            # merge the 2 dataframes.
            pca_df.index = samps
            df = pd.concat((df, pca_df), axis=1)

        if not plot:
            return df, background_pca_df

        from matplotlib import pyplot as plt
        import seaborn as sns
        colors = sns.color_palette('Set1', 4)

        cs = [colors[1 - int(v['depth_outlier'])] for v in sample_ranges.values()]
        ecs = ['none' if not v['ratio_outlier'] else 'k' for v in sample_ranges.values()]

        s = get_s(np.array([v['median_depth'] for v in sample_ranges.values()]))

        plt.scatter(depth, ratios, c=cs, edgecolors=ecs, s=s)

        for k, v in ((k, v) for k, v in sample_ranges.items()
                      if v['ratio_outlier'] or v['depth_outlier']):
          plt.text(v['median_depth'], v['het_ratio'], k, color=colors[1], fontsize=7)

        plt.xlabel('median depth')
        plt.ylabel('proportion het calls')
        plt.savefig(plot)
        return df, background_pca_df

    def ped_check(self, vcf, ncpus=1, plot=False, min_depth=5, each=1,
            prefix='',
            sites=op.join(op.dirname(__file__), '1kg.sites')):
        """
        Given the current pedigree and a VCF of genotypes, find sample-pairs where
        the relationship reported in the pedigree file do not match those inferred
        from the genotypes. Returns a dataframe containing all sample-pairs with
        columns for IBS0, IBS2, rel, IBS2*, pedigree_relatedness (relatedness
        coefficient expected)

        :param vcf str:  path to vcf
        :param min_depth int: minimum required depth.
        :return: pandas.DataFrame
        """
        import cyvcf2
        import numpy as np
        import pandas as pd
        vcf_str = vcf
        np.random.seed(42)

        samps = list(self.samples())
        if isinstance(vcf, basestring):
            vcf = cyvcf2.VCF(vcf, gts012=True, samples=[x.sample_id for x in samps])

        d = cyvcf2.par_relatedness(vcf_str,
                                   [x.sample_id for x in samps],
                                   ncpus,
                                   sites,
                                   min_depth=min_depth, each=each)
        cols = ['sample_a', 'sample_b']
        cols += [c for c in d if not c in ('sample_a', 'sample_b') and not c.endswith('error')]
        cols += [c for c in d if c.endswith('error')]
        if len(samps) > 200:
            print("large dataset: only reporting pedigree checks where in same"
                  + " family or relationship does not match expected",
                  file=sys.stderr)
        df = pd.DataFrame(d, columns=cols)
        a_samples = [self.get(a) for a in df.sample_a]
        assert all(not isinstance(a, list) for a in a_samples)
        b_samples = [self.get(b) for b in df.sample_b]
        assert all(not isinstance(b, list) for b in a_samples)
        df["pedigree_parents"] = np.array([self.relation(a, b) == 'parent-child' for a, b in
                                           zip(a_samples, b_samples)])
        df["pedigree_relatedness"] = np.array([self.relatedness_coefficient(a, b) for a, b in
                                               zip(df.sample_a, df.sample_b)])
        df['tmpibs0'] = df['ibs0'] / df['n'].astype(float)
        df["predicted_parents"] = df['tmpibs0'] < 0.012
        df["parent_error"] = df['pedigree_parents'] != df['predicted_parents']
        df["sample_duplication_error"] = (df['tmpibs0'] < 0.012) & (df['rel'] > 0.75)

        pr = df['pedigree_relatedness'][:]
        pr[pr < 0] = 0
        df["rel_difference"] = pr - df['rel']
        # make the column order a bit more sane.
        if len(samps) > 200:
            rd = np.abs(df['rel_difference']) > 0.17

            sampling_rate = 1 / (len(samps)**0.6)
            ru = (np.random.uniform(size=df.shape[0]) < sampling_rate)
            keep = df.eval('parent_error | sample_duplication_error | predicted_parents| @rd | @ru' +
                    '| (rel > 0.17) | (tmpibs0 < 0.04) | (pedigree_relatedness > 0)')

            same_fam = []
            for a, b in it.izip(a_samples, b_samples):
                same_fam.append(a.family_id == b.family_id)
            keep |= np.array(same_fam, dtype=bool)
            df['keep'] = keep

        def asum(a):
            return np.abs(a).sum()
            a = np.abs(a)
            return a[a > 0.08].sum()


        from matplotlib import pyplot as plt


        if not plot:
            df.drop('tmpibs0', axis=1, inplace=True)
            return df
        from matplotlib import pyplot as plt
        plt.close()
        import seaborn as sns
        sns.set_style('whitegrid')

        # get total rel_difference by sample. large values indicate the likely problem
        sub = df.eval('((rel > 0.1) & (pedigree_relatedness < 0.05)) | ((rel < 0.05) & (pedigree_relatedness > 0.1)) | (rel_difference > 0.1) | (rel_difference < -0.1)')
        da = df[sub].groupby('sample_a')['rel_difference'].agg(asum)
        db = df[sub].groupby('sample_b')['rel_difference'].agg(asum)
        diff = da.add(db, fill_value=0)
        diff.sort_values(inplace=True, ascending=False)

        diff.to_csv(plot.rsplit(".", 1)[0] + ".rel-difference.csv", index=True,
                index_label="sample", header=True)

        colors = [(0.85, 0.85, 0.85)] + sns.color_palette('Set1', len(set(df['pedigree_relatedness'])))
        n = df['n'] / df['n'].mean()
        if len(df) < 100:
            colors[0] = (0.3, 0.3, 0.3)

        mult = 24 if len(df) < 50 else 12

        fig, axesb = plt.subplots(2, 2, figsize=(12, 12))
        df['tmpibs2'] = df['ibs2'] / df['n'].astype(float)
        axes = axesb[0]

        for k, key in enumerate(('tmpibs0', 'tmpibs2')):

            for i, rc in enumerate(sorted(set(df['pedigree_relatedness']))):
                sel = df['pedigree_relatedness'] == rc
                src = ("%.3f" % rc).rstrip('0')
                # outline parent kid relationships
                ec = ['k' if p else 'none' for p in df['pedigree_parents'][sel]]
                axes[k].scatter(df['rel'][sel], df[key][sel],
                        c=colors[i], linewidth=1, edgecolors=ec,
                        s=((mult * (i > 0 or len(df) < 36)) + mult * n[sel]),
                        zorder=i,
                        alpha=0.80,
                        label="ped coef: %s" % src)
                axes[k].set_xlabel('coefficient of relatedness')
                axes[k].set_ylabel(key[3:])

        if prefix:
            fig.suptitle(prefix)
        xmin, xmax = axes[0].get_xlim()
        if xmin < -0.3:
            axes[0].set_xlim(xmin=-0.3)
        if xmax > 1.25:
            axes[0].set_xlim(xmax=1.25)

        axes = axesb[1]
        for k, key in enumerate(('ibs2', 'shared_hets')):
            for i, rc in enumerate(sorted(set(df['pedigree_relatedness']))):
                    sel = df['pedigree_relatedness'] == rc
                    src = ("%.3f" % rc).rstrip('0')
                    # outline parent kid relationships
                    ec = ['k' if p else 'none' for p in df['pedigree_parents'][sel]]
                    axes[k].scatter(df['ibs0'][sel], df[key][sel],
                            c=colors[i], linewidth=1, edgecolors=ec,
                            s=((mult * (i > 0 or len(df) < 36)) + mult * n[sel]),
                            zorder=i,
                            alpha=0.80,
                            label="ped coef: %s" % src)
                    axes[k].set_xlabel('ibs0')
                    axes[k].set_ylabel(key)

        plt.legend()

        if plot is True:
            plt.show()
        else:
            plt.savefig(plot)
        plt.close()
        df.drop(['tmpibs0', 'tmpibs2'], axis=1, inplace=True)
        return df

    def summary(self):
        atrios, aquads = 0, 0
        for family in self.families:
            aff, sex, trios, quads = self.families[family].summary()
            atrios += trios
            aquads += quads
            d = locals()
            d['affected'] = aff[PHENOTYPE.AFFECTED]
            d['unaffected'] = aff[PHENOTYPE.UNAFFECTED]
            d['unknown'] = aff[PHENOTYPE.UNKNOWN]
            d['sex_unknown'] = sex[SEX.UNKNOWN]
            d['male'] = sex[SEX.MALE]
            d['female'] = sex[SEX.FEMALE]
            print("""\
===============================================
family: '{family}' :: {trios} trios and {quads} quads
===============================================
---------
phenotype
---------
affected: {affected}
unaffected: {unaffected}
unknown: {unknown}

---
sex
---
male: {male}
female: {female}
unknown: {sex_unknown}""".format(**d))
        print(atrios, aquads)

if __name__ == "__main__":
    import doctest
    print(doctest.testmod(verbose=0))
