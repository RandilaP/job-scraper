"""
Caching utilities for job extraction system
Provides TTL cache, LRU cache, and cache statistics
"""

import logging
import time
from typing import Any, Callable, Dict, Optional, Tuple
from functools import wraps
from collections import OrderedDict
from threading import RLock


class TTLCache:
    """Thread-safe Time-To-Live cache with size limits"""
    
    def __init__(self, ttl: int = 3600, maxsize: int = 1000):
        """
        Initialize TTL cache
        
        Args:
            ttl: Time to live in seconds (default: 1 hour)
            maxsize: Maximum number of entries (default: 1000)
        """
        self.ttl = ttl
        self.maxsize = maxsize
        self.cache: OrderedDict[str, Tuple[Any, float]] = OrderedDict()
        self.lock = RLock()
        self.hits = 0
        self.misses = 0
        self.evictions = 0
    
    def get(self, key: str) -> Optional[Any]:
        """Get value from cache if not expired"""
        with self.lock:
            if key not in self.cache:
                self.misses += 1
                return None
            
            value, timestamp = self.cache[key]
            
            # Check if expired
            if time.time() - timestamp > self.ttl:
                del self.cache[key]
                self.evictions += 1
                self.misses += 1
                return None
            
            # Move to end (most recently used)
            self.cache.move_to_end(key)
            self.hits += 1
            return value
    
    def set(self, key: str, value: Any) -> None:
        """Set value in cache with current timestamp"""
        with self.lock:
            # Remove oldest if at capacity
            if key not in self.cache and len(self.cache) >= self.maxsize:
                oldest_key = next(iter(self.cache))
                del self.cache[oldest_key]
                self.evictions += 1
            
            self.cache[key] = (value, time.time())
            self.cache.move_to_end(key)
    
    def invalidate(self, key: str) -> None:
        """Remove key from cache"""
        with self.lock:
            if key in self.cache:
                del self.cache[key]
    
    def clear(self) -> None:
        """Clear all cache entries"""
        with self.lock:
            self.cache.clear()
            self.hits = 0
            self.misses = 0
            self.evictions = 0
    
    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        with self.lock:
            total_requests = self.hits + self.misses
            hit_rate = (self.hits / total_requests * 100) if total_requests > 0 else 0
            
            return {
                'size': len(self.cache),
                'maxsize': self.maxsize,
                'hits': self.hits,
                'misses': self.misses,
                'evictions': self.evictions,
                'hit_rate': f"{hit_rate:.2f}%",
                'ttl_seconds': self.ttl
            }
    
    def cleanup_expired(self) -> int:
        """Remove all expired entries and return count removed"""
        with self.lock:
            current_time = time.time()
            expired_keys = [
                key for key, (_, timestamp) in self.cache.items()
                if current_time - timestamp > self.ttl
            ]
            
            for key in expired_keys:
                del self.cache[key]
            
            if expired_keys:
                self.evictions += len(expired_keys)
            
            return len(expired_keys)


def ttl_cache(ttl: int = 3600, maxsize: int = 1000):
    """
    Decorator for caching function results with TTL
    
    Args:
        ttl: Time to live in seconds
        maxsize: Maximum cache entries
    
    Usage:
        @ttl_cache(ttl=300, maxsize=500)
        def expensive_function(arg1, arg2):
            return result
    """
    cache = TTLCache(ttl=ttl, maxsize=maxsize)
    
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            # Create cache key from args and kwargs
            # Only cache if all args are hashable
            try:
                cache_key = f"{func.__name__}:{args}:{sorted(kwargs.items())}"
            except TypeError:
                # If args not hashable, don't cache
                logging.debug(f"Cannot cache {func.__name__} - unhashable arguments")
                return func(*args, **kwargs)
            
            # Try to get from cache
            result = cache.get(cache_key)
            if result is not None:
                logging.debug(f"🎯 Cache hit: {func.__name__}")
                return result
            
            # Execute function and cache result
            logging.debug(f"🔍 Cache miss: {func.__name__}")
            result = func(*args, **kwargs)
            cache.set(cache_key, result)
            
            return result
        
        # Attach cache management functions
        wrapper.cache_clear = cache.clear
        wrapper.cache_stats = cache.get_stats
        wrapper.cache_cleanup = cache.cleanup_expired
        wrapper.cache_invalidate = cache.invalidate
        
        return wrapper
    
    return decorator


class CacheManager:
    """Global cache manager for monitoring all caches"""
    
    _instance = None
    _caches: Dict[str, TTLCache] = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(CacheManager, cls).__new__(cls)
        return cls._instance
    
    @classmethod
    def register_cache(cls, name: str, cache: TTLCache) -> None:
        """Register a cache for monitoring"""
        cls._caches[name] = cache
        logging.info(f"📊 Registered cache: {name} (TTL={cache.ttl}s, maxsize={cache.maxsize})")
    
    @classmethod
    def get_all_stats(cls) -> Dict[str, Dict[str, Any]]:
        """Get statistics for all registered caches"""
        return {
            name: cache.get_stats()
            for name, cache in cls._caches.items()
        }
    
    @classmethod
    def clear_all_caches(cls) -> None:
        """Clear all registered caches"""
        for name, cache in cls._caches.items():
            cache.clear()
            logging.info(f"🧹 Cleared cache: {name}")
    
    @classmethod
    def cleanup_all_expired(cls) -> Dict[str, int]:
        """Clean up expired entries in all caches"""
        results = {}
        for name, cache in cls._caches.items():
            count = cache.cleanup_expired()
            if count > 0:
                logging.info(f"🧹 Cleaned {count} expired entries from {name}")
            results[name] = count
        return results
    
    @classmethod
    def log_cache_stats(cls) -> None:
        """Log statistics for all caches"""
        logging.info("=" * 60)
        logging.info("📊 CACHE STATISTICS")
        logging.info("=" * 60)
        
        total_hits = 0
        total_misses = 0
        total_size = 0
        
        for name, cache in cls._caches.items():
            stats = cache.get_stats()
            total_hits += stats['hits']
            total_misses += stats['misses']
            total_size += stats['size']
            
            logging.info(f"\n{name}:")
            logging.info(f"  Size: {stats['size']}/{stats['maxsize']}")
            logging.info(f"  Hits: {stats['hits']}")
            logging.info(f"  Misses: {stats['misses']}")
            logging.info(f"  Hit Rate: {stats['hit_rate']}")
            logging.info(f"  Evictions: {stats['evictions']}")
            logging.info(f"  TTL: {stats['ttl_seconds']}s")
        
        overall_requests = total_hits + total_misses
        overall_hit_rate = (total_hits / overall_requests * 100) if overall_requests > 0 else 0
        
        logging.info(f"\nOVERALL:")
        logging.info(f"  Total Caches: {len(cls._caches)}")
        logging.info(f"  Total Entries: {total_size}")
        logging.info(f"  Total Hits: {total_hits}")
        logging.info(f"  Total Misses: {total_misses}")
        logging.info(f"  Overall Hit Rate: {overall_hit_rate:.2f}%")
        logging.info("=" * 60)


# Convenience function for simple memoization
def memoize(func: Callable) -> Callable:
    """
    Simple memoization decorator (no TTL, no size limit)
    Use for functions with stable, frequently accessed results
    
    Usage:
        @memoize
        def get_constant_value():
            return expensive_calculation()
    """
    cache = {}
    
    @wraps(func)
    def wrapper(*args, **kwargs):
        try:
            cache_key = (args, tuple(sorted(kwargs.items())))
        except TypeError:
            return func(*args, **kwargs)
        
        if cache_key not in cache:
            cache[cache_key] = func(*args, **kwargs)
        
        return cache[cache_key]
    
    wrapper.cache_clear = cache.clear
    wrapper.cache_info = lambda: {'size': len(cache)}
    
    return wrapper
