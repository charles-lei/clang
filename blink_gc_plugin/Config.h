// Copyright 2014 The Chromium Authors. All rights reserved.
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

// This file defines the names used by GC infrastructure.

#ifndef TOOLS_BLINK_GC_PLUGIN_CONFIG_H_
#define TOOLS_BLINK_GC_PLUGIN_CONFIG_H_

#include "clang/AST/AST.h"

const char kNewOperatorName[] = "operator new";
const char kTraceName[] = "trace";
const char kTraceAfterDispatchName[] = "traceAfterDispatch";
const char kRegisterWeakMembersName[] = "registerWeakMembers";
const char kHeapAllocatorName[] = "HeapAllocator";

class Config {
 public:
  static bool IsMember(const std::string& name) {
    return name == "Member";
  }

  static bool IsWeakMember(const std::string& name) {
    return name == "WeakMember";
  }

  static bool IsMemberHandle(const std::string& name) {
    return IsMember(name) ||
           IsWeakMember(name);
  }

  static bool IsPersistent(const std::string& name) {
    return name == "Persistent";
  }

  static bool IsPersistentHandle(const std::string& name) {
    return IsPersistent(name) ||
           IsPersistentGCCollection(name);
  }

  static bool IsRefPtr(const std::string& name) {
    return name == "RefPtr";
  }

  static bool IsOwnPtr(const std::string& name) {
    return name == "OwnPtr";
  }

  static bool IsWTFCollection(const std::string& name) {
    return name == "Vector" ||
           name == "HashSet" ||
           name == "HashMap" ||
           name == "HashCountedSet" ||
           name == "ListHashSet" ||
           name == "Deque";
  }

  static bool IsPersistentGCCollection(const std::string& name) {
    return name == "PersistentHeapVector" ||
           name == "PersistentHeapHashMap" ||
           name == "PersistentHeapHashSet";
  }

  static bool IsGCCollection(const std::string& name) {
    return name == "HeapVector" ||
           name == "HeapHashMap" ||
           name == "HeapHashSet" ||
           IsPersistentGCCollection(name);
  }

  static bool IsGCFinalizedBase(const std::string& name) {
    return name == "GarbageCollectedFinalized" ||
           name == "RefCountedGarbageCollected";
  }

  static bool IsGCBase(const std::string& name) {
    return name == "GarbageCollected" ||
           IsGCFinalizedBase(name);
  }

  static bool IsTraceMethod(clang::CXXMethodDecl* method,
                            bool* isTraceAfterDispatch = 0) {
    const std::string& name = method->getNameAsString();
    if (name == kTraceName || name == kTraceAfterDispatchName) {
      if (isTraceAfterDispatch)
        *isTraceAfterDispatch = (name == kTraceAfterDispatchName);
      return true;
    }
    return false;
  }

  static bool StartsWith(const std::string& str, const std::string& prefix) {
    if (prefix.size() > str.size())
      return false;
    return str.compare(0, prefix.size(), prefix) == 0;
  }

  static bool EndsWith(const std::string& str, const std::string& suffix) {
    if (suffix.size() > str.size())
      return false;
    return str.compare(str.size() - suffix.size(), suffix.size(), suffix) == 0;
  }
};

#endif  // TOOLS_BLINK_GC_PLUGIN_CONFIG_H_