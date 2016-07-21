import os
import sys
import time
import json
from collections import defaultdict
from random import randint, choice

from elasticsearch import Elasticsearch, helpers

# pass host ex : http://192.168.99.100:9203
es_host = sys.argv[1]
mv_host = sys.argv[2]

# cluster to run against
es = Elasticsearch(es_host,http_auth=('es_admin', 'password'))

# reporting cluster
monitoring_es = Elasticsearch(mv_host,http_auth=('es_admin', 'password'))

# get cluster name
cluster_name = es.info()['cluster_name']

# index name pattern
INDEX = cluster_name + '-%s'


with open('mapping2.json', 'r') as m:
    MAPPING = json.load(m)

ACTIONS = [
    (
        'create_index', True,
        lambda i: es.indices.create(
            index=INDEX % i,
            body={
                'settings': {'number_of_shards': randint(1, 6), 'number_of_replicas': 0},
                'mappings': MAPPING,
            },request_timeout=250
        )
    ),
    (
        'add_type', False,
        lambda i: es.index(
            index=INDEX % randint(0, counters['create_index']),
            doc_type='type-%d' % i,
            body={'some': 'data'}
        )
    ),
    (
        'add_field', False,
        lambda i: es.index(
            index=INDEX % randint(0, counters['create_index']),
            doc_type='type-%d' % randint(0, counters['add_type']),
            body={'field%d' % i: 'data'}
        )
    ),
    (
        'add_alias', False,
        lambda i: es.indices.put_alias(
            index=INDEX % randint(0, counters['create_index']),
            name='alias-%i' % i
        )
    ),
    #(
    #    'add_template', True,
    #    lambda i: es.indices.put_template(
    #        name='template-%i' % i,
    #        body={
    #            'template': 'test-*',
    #            'settings': {
    #                'number_of_shards': 1,
    #                'number_of_replicas': 0,
    #            },
    #            'mappings': MAPPING
    #        }
    #    )
    #),
]

counters = defaultdict(int)

# clear indices
es.indices.delete(index=INDEX % '*', ignore=404)
es.indices.delete_template(name='template-*', ignore=404)
# get cluster name
cluster_name = es.info()['cluster_name']

if not monitoring_es.indices.exists(index='events'):
    monitoring_es.indices.create(
        index='events',
        body={
            'settings': {'number_of_shards': 1, 'number_of_replicas': 0},
            'mappings': {
                'cs': {
                    'properties': {
                        'timestamp': {'type': 'date'},
                        'cluster': {'type': 'string', 'index': 'not_analyzed'},
                    }
                },
                'event': {
                    'properties': {
                        'timestamp': {'type': 'date'},
                        'action': {'type': 'string', 'index': 'not_analyzed'},
                        'cluster': {'type': 'string', 'index': 'not_analyzed'},
                    }
                },
            }
        }
    )

# create at least one index/type
ACTIONS[0][2](0)
ACTIONS[1][2](0)


cluster_state_size = 0

def run():
    for i in range(100000):
        action, big, f = choice(ACTIONS)

        if i % 300 == 0:
            cs = es.cluster.state()
            cluster_state_size = len(json.dumps(cs))
            indices = len(cs['metadata']['indices'])
            yield {
                '_type': 'cs',
                'cluster': cluster_name,
                'timestamp': int(time.time() * 1000),
                'cluster_state_size': cluster_state_size,
                'indices': indices,
            }

        if big and randint(0, cluster_state_size) > 30000:
            # cluster state is already big enough
            continue

        counters[action] = counters[action] + 1

        start = time.time()
        f(counters[action])
        duration = time.time() - start

        yield {
            'cluster': cluster_name,
            'action': action,
            'duration': duration,
            'timestamp': int(time.time() * 1000),
            'big': big,
        }

for ok, info in helpers.streaming_bulk(monitoring_es, run(), index='events', doc_type='event', chunk_size=50):
    sys.stdout.write('.')
    sys.stdout.flush()
print

