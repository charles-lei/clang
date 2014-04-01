#!/usr/bin/env python
# Copyright 2014 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import argparse, os, sys, json, subprocess, pickle, StringIO

parser = argparse.ArgumentParser(
  description =
    "Process the Blink points-to graph generated by the Blink GC plugin.")

parser.add_argument(
  '-', dest='use_stdin', action='store_true',
  help='Read JSON graph files from stdin')

parser.add_argument(
  '-c', '--detect-cycles', action='store_true',
  help='Detect cycles containing GC roots')

parser.add_argument(
  '-s', '--print-stats', action='store_true',
  help='Statistics about ref-counted and traced objects')

parser.add_argument(
  '-v', '--verbose', action='store_true',
  help='Verbose output')

parser.add_argument(
  '--ignore-cycles', default=None, metavar='FILE',
  help='File with cycles to ignore')

parser.add_argument(
  '--ignore-classes', nargs='*', default=[], metavar='CLASS',
  help='Classes to ignore when detecting cycles')

parser.add_argument(
  '--pickle-graph', default=None, metavar='FILE',
  help='File to read/save the graph from/to')

parser.add_argument(
  'files', metavar='FILE_OR_DIR', nargs='*', default=[],
  help='JSON graph files or directories containing them')

# Command line args after parsing.
args = None

# Map from node labels to nodes.
graph = {}

# Set of root nodes.
roots = []

# List of cycles to ignore.
ignored_cycles = []

# Global flag to determine exit code.
global_reported_error = False

def set_reported_error(value):
  global global_reported_error
  global_reported_error = value

def reported_error():
  return global_reported_error

def log(msg):
  if args.verbose:
    print msg

global_inc_copy = 0
def inc_copy():
  global global_inc_copy
  global_inc_copy += 1

def get_node(name):
  return graph.setdefault(name, Node(name))

ptr_types = ('raw', 'ref', 'mem')

def inc_ptr(dst, ptr):
  if ptr in ptr_types:
    node = graph.get(dst)
    if not node: return
    node.counts[ptr] += 1

def add_counts(s1, s2):
  for (k, v) in s2.iteritems():
    s1[k] += s2[k]

# Representation of graph nodes. Basically a map of directed edges.
class Node:
  def __init__(self, name):
    self.name = name
    self.edges = {}
    self.reset()
  def __repr__(self):
    return "%s(%s) %s" % (self.name, self.visited, self.edges)
  def update_node(self, decl):
    # Currently we don't track any node info besides its edges.
    pass
  def update_edge(self, e):
    new_edge = Edge(**e)
    edge = self.edges.get(new_edge.key)
    if edge:
      # If an edge exist, its kind is the strongest of the two.
      edge.kind = max(edge.kind, new_edge.kind)
    else:
      self.edges[new_edge.key] = new_edge
  def super_edges(self):
    return [ e for e in self.edges.itervalues() if e.is_super() ]
  def subclass_edges(self):
    return [ e for e in self.edges.itervalues() if e.is_subclass() ]
  def reset(self):
    self.cost = sys.maxint
    self.visited = False
    self.path = None
    self.counts = {}
    for ptr in ptr_types:
      self.counts[ptr] = 0
  def update_counts(self):
    for e in self.edges.itervalues():
      inc_ptr(e.dst, e.ptr)

# Representation of directed graph edges.
class Edge:
  def __init__(self, **decl):
    self.src = decl['src']
    self.dst = decl['dst']
    self.lbl = decl['lbl']
    self.ptr = decl['ptr']
    self.kind = decl['kind'] # 0 = weak, 1 = strong, 2 = root
    self.loc = decl['loc']
    # The label does not uniquely determine an edge from a node. We
    # define the semi-unique key to be the concatenation of the
    # label and dst name. This is sufficient to track the strongest
    # edge to a particular type. For example, if the field A::m_f
    # has type HashMap<WeakMember<B>, Member<B>> we will have a
    # strong edge with key m_f#B from A to B.
    self.key = '%s#%s' % (self.lbl, self.dst)
  def __repr__(self):
    return '%s (%s) => %s' % (self.src, self.lbl, self.dst)
  def is_root(self):
    return self.kind == 2
  def is_weak(self):
    return self.kind == 0
  def keeps_alive(self):
    return self.kind > 0
  def is_subclass(self):
    return self.lbl.startswith('<subclass>')
  def is_super(self):
    return self.lbl.startswith('<super>')

def parse_file(filename):
  obj = json.load(open(filename))
  return obj

def build_graphs_in_dir(dirname):
  # TODO: Use plateform independent code, eg, os.walk
  files = subprocess.check_output(
    ['find', dirname, '-name', '*.graph.json']).split('\n')
  log("Found %d files" % len(files))
  for f in files:
    f.strip()
    if len(f) < 1:
      continue
    build_graph(f)

def build_graph(filename):
  for decl in parse_file(filename):
    if decl.has_key('name'):
      # Add/update a node entry
      name = decl['name']
      node = get_node(name)
      node.update_node(decl)
    else:
      # Add/update an edge entry
      name = decl['src']
      node = get_node(name)
      node.update_edge(decl)

# Copy all non-weak edges from super classes to their subclasses.
# This causes all fields of a super to be considered fields of a
# derived class without tranitively relating derived classes with
# each other. For example, if B <: A, C <: A, and for some D, D => B,
# we don't want that to entail that D => C.
def copy_super_edges(edge):
  if edge.is_weak() or not edge.is_super():
    return
  inc_copy()
  # Make the super-class edge weak (prohibits processing twice).
  edge.kind = 0
  # If the super class is not in our graph exit early.
  super_node = graph.get(edge.dst)
  if super_node is None: return
  # Recursively copy all super-class edges.
  for e in super_node.super_edges():
    copy_super_edges(e)
  # Copy strong super-class edges (ignoring sub-class edges) to the sub class.
  sub_node = graph[edge.src]
  for e in super_node.edges.itervalues():
    if e.keeps_alive() and not e.is_subclass():
      new_edge = Edge(
        src = super_node.name,
        dst = e.dst,
        lbl = '%s <: %s' % (super_node.name, e.lbl),
        ptr = e.ptr,
        kind = e.kind,
        loc = e.loc,
      )
      sub_node.edges[new_edge.key] = new_edge
  # Add a strong sub-class edge.
  sub_edge = Edge(
    src = super_node.name,
    dst = sub_node.name,
    lbl = '<subclass>',
    ptr = edge.ptr,
    kind = 1,
    loc = edge.loc,
  )
  super_node.edges[sub_edge.key] = sub_edge

def complete_graph():
  for node in graph.itervalues():
    for edge in node.super_edges():
      copy_super_edges(edge)
    for edge in node.edges.itervalues():
      if edge.is_root():
        roots.append(edge)
  log("Copied edges down <super> edges for %d graph nodes" % global_inc_copy)

def reset_graph():
  for n in graph.itervalues():
    n.reset()

def shortest_path(start, end):
  start.cost = 0
  minlist = [start]
  while len(minlist) > 0:
    minlist.sort(key=lambda n: -n.cost)
    current = minlist.pop()
    current.visited = True
    if current == end or current.cost >= end.cost + 1:
      return
    for e in current.edges.itervalues():
      if not e.keeps_alive():
        continue
      dst = graph.get(e.dst)
      if dst is None or dst.visited:
        continue
      if current.cost < dst.cost:
        dst.cost = current.cost + 1
        dst.path = e
      minlist.append(dst)

def detect_cycles():
  for root_edge in roots:
    reset_graph()
    # Mark ignored classes as already visited
    for ignore in args.ignore_classes:
      name = ignore.find("::") > 0 and ignore or ("WebCore::" + ignore)
      node = graph.get(name)
      if node:
        node.visited = True
    src = graph[root_edge.src]
    dst = graph.get(root_edge.dst)
    if src.visited:
      continue
    if root_edge.dst == "WTF::String":
      continue
    if dst is None:
      print "\nPersistent root to incomplete destination object:"
      print root_edge
      set_reported_error(True)
      continue
    # Find the shortest path from the root target (dst) to its host (src)
    shortest_path(dst, src)
    if src.cost < sys.maxint:
      report_cycle(root_edge)

def is_ignored_cycle(cycle):
  for block in ignored_cycles:
    if block_match(cycle, block):
      return True

def block_match(b1, b2):
  if len(b1) != len(b2):
    return False
  for (l1, l2) in zip(b1, b2):
    if l1 != l2:
      return False
  return True

def report_cycle(root_edge):
  dst = graph[root_edge.dst]
  path = []
  edge = root_edge
  dst.path = None
  while edge:
    path.append(edge)
    edge = graph[edge.src].path
  path.append(root_edge)
  path.reverse()
  # Find the max loc length for pretty printing.
  max_loc = 0
  for p in path:
    if len(p.loc) > max_loc:
      max_loc = len(p.loc)
  out = StringIO.StringIO()
  for p in path[:-1]:
    print >>out, (p.loc + ':').ljust(max_loc + 1), p
  sout = out.getvalue()
  if not is_ignored_cycle(sout):
    print "\nFound a potentially leaking cycle starting from a GC root:\n", sout
    set_reported_error(True)

def load_graph():
  global graph
  global roots
  log("Reading graph from pickled file: " + args.pickle_graph)
  dump = pickle.load(open(args.pickle_graph, 'rb'))
  graph = dump[0]
  roots = dump[1]

def save_graph():
  log("Saving graph to pickle file: " + args.pickle_graph)
  dump = (graph, roots)
  pickle.dump(dump, open(args.pickle_graph, 'wb'))

def read_ignored_cycles():
  global ignored_cycles
  if not args.ignore_cycles:
    return
  log("Reading ignored cycles from file: " + args.ignore_cycles)
  block = []
  for l in open(args.ignore_cycles):
    line = l.strip()
    if not line or line.startswith('Found'):
      if len(block) > 0:
        ignored_cycles.append(block)
      block = []
    else:
      block += l
  if len(block) > 0:
    ignored_cycles.append(block)

gc_bases = (
  'WebCore::GarbageCollected',
  'WebCore::GarbageCollectedFinalized',
  'WebCore::GarbageCollectedMixin',
)
ref_bases = (
  'WTF::RefCounted',
  'WTF::ThreadSafeRefCounted',
)
gcref_bases = (
  'WebCore::RefCountedGarbageCollected',
  'WebCore::ThreadSafeRefCountedGarbageCollected',
)
ref_mixins = (
  'WebCore::EventTarget',
  'WebCore::EventTargetWithInlineData',
  'WebCore::ActiveDOMObject',
)

def print_stats():
  gcref_managed = []
  ref_managed = []
  gc_managed = []
  hierarchies = []

  for node in graph.itervalues():
    node.update_counts()
    for sup in node.super_edges():
      if sup.dst in gcref_bases:
        gcref_managed.append(node)
      elif sup.dst in ref_bases:
        ref_managed.append(node)
      elif sup.dst in gc_bases:
        gc_managed.append(node)

  groups = [("GC manged   ", gc_managed),
            ("ref counted ", ref_managed),
            ("in transition", gcref_managed)]
  total = sum([len(g) for (s,g) in groups])
  for (s, g) in groups:
    percent = len(g) * 100 / total
    print "%2d%% is %s (%d hierarchies)" % (percent, s, len(g))

  for base in gcref_managed:
    stats = dict({ 'classes': 0, 'ref-mixins': 0 })
    for ptr in ptr_types: stats[ptr] = 0
    hierarchy_stats(base, stats)
    hierarchies.append((base, stats))

  print "\nHierarchies in transition (RefCountedGarbageCollected):"
  hierarchies.sort(key=lambda (n,s): -s['classes'])
  for (node, stats) in hierarchies:
    total = stats['mem'] + stats['ref'] + stats['raw']
    print (
      "%s %3d%% of %-30s: %3d cls, %3d mem, %3d ref, %3d raw, %3d ref-mixins" %
      (stats['ref'] == 0 and stats['ref-mixins'] == 0 and "*" or " ",
       total == 0 and 100 or stats['mem'] * 100 / total,
       node.name.replace('WebCore::', ''),
       stats['classes'],
       stats['mem'],
       stats['ref'],
       stats['raw'],
       stats['ref-mixins'],
     ))

def hierarchy_stats(node, stats):
  if not node: return
  stats['classes'] += 1
  add_counts(stats, node.counts)
  for edge in node.super_edges():
    if edge.dst in ref_mixins:
      stats['ref-mixins'] += 1
  for edge in node.subclass_edges():
    hierarchy_stats(graph.get(edge.dst), stats)

def main():
  global args
  args = parser.parse_args()
  if not (args.detect_cycles or args.print_stats):
    print "Please select an operation to perform (eg, -c to detect cycles)"
    parser.print_help()
    return 1
  if args.pickle_graph and os.path.isfile(args.pickle_graph):
    load_graph()
  else:
    if args.use_stdin:
      log("Reading files from stdin")
      for f in sys.stdin:
        build_graph(f.strip())
    else:
      log("Reading files and directories from command line")
      if len(args.files) == 0:
        print "Please provide files or directores for building the graph"
        parser.print_help()
        return 1
      for f in args.files:
        if os.path.isdir(f):
          log("Building graph from files in directory: " + f)
          build_graphs_in_dir(f)
        else:
          log("Building graph from file: " + f)
          build_graph(f)
    log("Completing graph construction (%d graph nodes)" % len(graph))
    complete_graph()
    if args.pickle_graph:
      save_graph()
  if args.detect_cycles:
    read_ignored_cycles()
    log("Detecting cycles containg GC roots")
    detect_cycles()
  if args.print_stats:
    log("Printing statistics")
    print_stats()
  if reported_error():
    return 1
  return 0

if __name__ == '__main__':
  sys.exit(main())