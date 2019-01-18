#!/usr/bin/env python3
# -*- coding: utf-8 -*-
#
#This file is part of minifold
#Copyright © 2018 Nokia Corporation and/or its subsidiary(-ies). All rights reserved. *
#
# Authors:
#   Marc-Olivier Buob <marc-olivier.buob@nokia-bell-labs.com>

import datetime, functools, json, os, pickle, sys, traceback

from enum   import Enum
from pprint import pprint

from minifold.connector     import Connector
from minifold.filesystem    import check_writable_directory, mtime, mkdir, rm
from minifold.query         import Query, ACTION_READ
from minifold.log           import Log

MINIFOLD_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".minifold", "cache")
CACHE_LIFETIME     = datetime.timedelta(days = 3)

# TODO:
# Clarify how the keys of the cache are defined.
#
# Those keys should depend on:
# 1) the Connector itself (including its configuration),
#    as well as its underlying Connectors.
#    ==>  define Connector.__hash__ consequently.
# 2) the Query issued to the connector

# TODO:
# For the moment, the cache is only used if the exact same Query
# was issued over the past. But we should be able to reuse the cache
# if a less strict query has been issued, and use
# Connector.reshape_entries afterwards.

class CacheConnector(Connector):
    def __init__(self, child):
        self.child = child

    def callback_read(self, query) -> tuple:
        raise RuntimeError("Must be overloaded")

    def callback_write(self, query, data):
        raise RuntimeError("Must be overloaded")

    def clear_query(self, query :Query):
        pass

    def clear_cache(self):
        pass

    def read(self, query :Query):
        (data, success) = (None, False)
        try:
            data = self.callback_read(query)
            success = True
            print(str(data))
            print(success)
        except:
            Log.error(
                "CacheConnector.read(%s): Cannot read cache:\n%s" % (
                    query,
                    traceback.format_exc()
                )
            )
        return (data, success)

    def write(self, query :Query, data) -> bool:
        success = True
        try:
            self.callback_write(query, data)
        except:
            Log.error(
                "CacheConnector.write(%s, %s): Cannot write cache:\n%s" % (
                    traceback.format_exc(),
                    query,
                    data
                )
            )
            success = False
        return success

    def is_cached(self, query :Query) -> bool:
        raise RuntimeError("Must be overloaded")

    def is_cachable(self, query :Query, data) -> bool:
        return True

    def query(self, query :Query):
        Log.debug("Connector.query(%s)" % query)
        (data, success) = (None, False)
        if self.is_cached(query):
            (data, success) = self.read(query)
            Log.warning("CacheConnector.query(%s): Unreadable cache" % query)
        if not success:
            data = self.child.query(query)
        if query.action == ACTION_READ and self.is_cachable(query, data):
            self.write(query, data)
        return self.answer(query, data)

def make_cache_dir(base_dir :str = MINIFOLD_CACHE_DIR, connector: Connector = None):
    return os.path.join(base_dir, connector.__class__.__name__) if connector else base_dir

class StorageCacheConnector(CacheConnector):
    def __init__(
        self,
        child : Connector,
        callback_load = None,
        callback_dump = None,
        lifetime :datetime.timedelta = CACHE_LIFETIME,
        cache_dir  = None,
        read_mode  = "r",
        write_mode = "w",
        extension  = ""
    ):
        Log.debug(StorageCacheConnector)
        super().__init__(child)
        self.callback_load = callback_load
        self.callback_dump = callback_dump
        self.lifetime   = lifetime
        self.cache_dir  = cache_dir if cache_dir else \
                          make_cache_dir(MINIFOLD_CACHE_DIR, child)
        self.read_mode  = read_mode
        self.write_mode = write_mode
        self.extension  = extension

    def make_cache_filename(self, query :Query) -> str:
        return os.path.join(self.cache_dir, str(query) + self.extension)

    def clear_query(self, query :Query):
        cache_filename = self.make_cache_filename(query)
        if os.path.exists(cache_filename):
            Log.debug("StorageCacheConnector: Removing query [%s]" % cache_filename)
            rm(cache_filename)

    def clear_cache(self):
        if os.path.exists(self.cache_dir) and os.path.isdir(self.cache_dir):
            Log.debug("StorageCacheConnector: Removing cache [%s]" % self.cache_dir)
            rm(self.cache_dir, recursive=True)

    @staticmethod
    def is_fresh_cache(cache_filename :str, lifetime :datetime.timedelta) -> bool:
        is_fresh = True
        if lifetime:
            t_now = datetime.datetime.utcnow()
            t_cache = mtime(cache_filename)
            is_fresh = (t_now - t_cache) < lifetime
            Log.debug("t_now(%s) - t_cache(%s) = %s ?< lifetime %s" % (
                t_now, t_cache, (t_now - t_cache), lifetime
            ))
        return is_fresh

    def is_cached(self, query :Query) -> bool:
        ret = False
        cache_filename = self.make_cache_filename(query)
        if os.path.exists(cache_filename):
            ret = StorageCacheConnector.is_fresh_cache(cache_filename, self.lifetime)
        return ret

    def callback_read(self, query :Query) -> tuple:
        (data, success) = (None, False)
        cache_filename = self.make_cache_filename(query)
        if self.is_cached(query):
            with open(cache_filename, self.read_mode) as f:
                data = self.callback_load(f)
                success = True
        return (data, success)

    def callback_write(self, query :Query, data):
        cache_filename = self.make_cache_filename(query)
        directory = os.path.dirname(cache_filename)
        mkdir(directory)
        check_writable_directory(directory)
        with open(cache_filename, self.write_mode) as f:
            self.callback_dump(data, f)

class PickleCacheConnector(StorageCacheConnector):
    def __init__(self, child, lifetime = CACHE_LIFETIME, cache_dir = None):
        super().__init__(
            child,
            pickle.load, pickle.dump,
            lifetime, cache_dir,
            "rb", "wb", ".pkl"
        )

class JsonCacheConnector(StorageCacheConnector):
    def __init__(self, child, lifetime = CACHE_LIFETIME, cache_dir = None):
        super().__init__(
            child,
            json.load, json.dump,
            lifetime, cache_dir,
            "r", "w", ".json"
        )

