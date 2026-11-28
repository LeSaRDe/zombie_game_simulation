"""Resource quantities and reservations are values, never duplicate stocks."""
from dataclasses import dataclass
from .values import check_fields, number

RESOURCES = ("FOOD", "MEDICAL_SUPPLY", "MATERIAL")


@dataclass(frozen=True)
class ResourceQuantities:
    food: int = 0
    medical_supply: int = 0
    material: int = 0
    _present: frozenset[str] = frozenset(RESOURCES)

    def __post_init__(self):
        for name, value in zip(RESOURCES, (self.food, self.medical_supply, self.material)):
            number(value, name, integer=True)

    @classmethod
    def from_record(cls, record):
        present = check_fields(record, RESOURCES, "resource quantities")
        return cls(*(record.get(name, 0) for name in RESOURCES), present)

    def to_record(self):
        return {key: value for key, value in zip(RESOURCES, (self.food, self.medical_supply, self.material)) if key in self._present}

    @property
    def total(self):
        return self.food + self.medical_supply + self.material

    def quantity(self, resource):
        return dict(zip(RESOURCES, (self.food, self.medical_supply, self.material)))[resource]


@dataclass(frozen=True)
class Inventory:
    quantities: ResourceQuantities
    reserved: ResourceQuantities
    capacity: int

    def __post_init__(self):
        from .values import CodecError
        number(self.capacity, "carry_capacity", integer=True)
        if self.quantities.total > self.capacity:
            raise CodecError("Inventory exceeds carrying capacity")
        if any(self.reserved.quantity(key) > self.quantities.quantity(key) for key in RESOURCES):
            raise CodecError("Reservations exceed resource stock")

    def available(self, resource):
        return self.quantities.quantity(resource) - self.reserved.quantity(resource)
