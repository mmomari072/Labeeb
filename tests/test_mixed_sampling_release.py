import numpy as np
import pytest

from labeeb import Attribute, Database, Derived, Normal, OAT, Uniform, DatabaseError


def test_lhs_shared_samples_match_across_oat_rows():
    db = Database(attributes=[Attribute('x', sampling=Uniform(0, 1)),
                              Attribute('z', sampling=OAT([1, 2, 3]))],
                  n=10, seed=42, method='lhs', random_reuse='shared')
    assert list(db['x'][:10]) == list(db['x'][10:20]) == list(db['x'][20:])
    assert sorted(int(v * 10) for v in db['x'][:10]) == list(range(10))


def test_lhs_independent_is_stratified_per_oat_row():
    db = Database(attributes=[Attribute('x', sampling=Uniform(0, 1)),
                              Attribute('z', sampling=OAT([1, 2]))],
                  n=10, seed=42, method='lhs')
    assert list(db['x'][:10]) != list(db['x'][10:])
    for block in (db['x'][:10], db['x'][10:]):
        assert sorted(int(v * 10) for v in block) == list(range(10))


def test_derived_chain_is_order_independent_and_updates():
    db = Database(attributes=[Attribute('w', sampling=Derived('v + z')),
                              Attribute('v', sampling=Derived('2 * x')),
                              Attribute('z', sampling=OAT([1, 2])),
                              Attribute('x', sampling=Normal(0, 1))], n=2, seed=4)
    db.set_row(0, {'x': 5})
    assert db['v'][0] == 10
    assert db['w'][0] == 11


def test_custom_sampler_receives_seeded_rng():
    class Custom:
        def draw(self, size, rng):
            return rng.uniform(size=size)
    def build():
        return Database(attributes=[Attribute('x', sampling=Custom())], n=4, seed=8)
    assert list(build()['x']) == list(build()['x'])


@pytest.mark.parametrize('specs', [
    [Attribute('a', sampling=Derived('b + 1')), Attribute('b', sampling=Derived('a + 1'))],
    [Attribute('a', sampling=Derived(lambda r: r['missing'], dependencies=['missing']))],
])
def test_bad_dependencies_are_rejected(specs):
    with pytest.raises(DatabaseError):
        Database(attributes=specs, n=2)


def test_normal_lhs_and_callable_derived_refresh():
    from statistics import NormalDist
    db = Database(attributes=[
        Attribute('w', sampling=Derived(lambda r: r['v'] + 1, dependencies=['v'])),
        Attribute('v', sampling=Derived('x * 2')),
        Attribute('x', sampling=Normal(5, 2)),
    ], n=20, seed=42, method='lhs')
    probabilities = [NormalDist(5, 2).cdf(x) for x in db['x']]
    assert sorted(int(p * 20) for p in probabilities) == list(range(20))
    db.set_row(0, {'x': 3})
    assert db['w'][0] == 7


@pytest.mark.parametrize('options', [{'method': 'bad'}, {'random_reuse': 'bad'}])
def test_invalid_sampling_options_fail(options):
    with pytest.raises(DatabaseError):
        Database(attributes=[Attribute('x', sampling=Uniform(0, 1))], n=3, **options)


@pytest.mark.parametrize('spec', [Normal(float('nan'), 1), Normal(0, -1), Uniform(2, 1)])
def test_invalid_distribution_parameters_fail(spec):
    with pytest.raises(DatabaseError):
        Database(attributes=[Attribute('x', sampling=spec)], n=3)


def test_custom_ppf_supports_lhs_and_legacy_sampler_rejects_lhs():
    class Distribution:
        def ppf(self, probabilities):
            return np.asarray(probabilities) * 10
    db = Database(attributes=[Attribute('x', sampling=Distribution())], n=5, method='lhs')
    assert sorted(int(x / 2) for x in db['x']) == list(range(5))
    with pytest.raises(DatabaseError, match='LHS requires'):
        Database(attributes=[Attribute('x', sampling=lambda n: [0] * n)], n=5, method='lhs')


def test_shared_monte_carlo_is_reproducible():
    def build():
        return Database(attributes=[Attribute('x', sampling=Normal(0, 1)),
                                    Attribute('z', sampling=OAT([1, 2]))],
                        n=5, seed=9, random_reuse='shared')
    first = build()
    assert list(first['x'][:5]) == list(first['x'][5:])
    assert list(first['x']) == list(build()['x'])
