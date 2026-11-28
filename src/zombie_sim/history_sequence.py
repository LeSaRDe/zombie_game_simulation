"""Bounded-payload sequence views over the complete durable event ledger.

Only eight-byte event IDs, a few decoded pages, and the current uncommitted
batch stay resident. Full observations and outcomes remain losslessly in SQLite.
"""
from __future__ import annotations
from array import array
from collections import OrderedDict
from collections.abc import Sequence
from copy import deepcopy
from fractions import Fraction


class LedgerRecords(Sequence):
    def __init__(self,history,kind=None):
        self.history=history;self.kind=kind;self.pending=[];self.pages=OrderedDict()
        self.indices=array("Q",history.event_positions(kind))

    def _record(self,record):
        if self.kind=="decision":
            return {key:value for key,value in record.items() if key not in {"kind","revision","causes"}}
        if self.kind=="random_draw":
            return {key:value for key,value in record.items() if key not in {"id","kind","revision","causes"}}
        return record

    def append(self,record):self.pending.append(record)
    def extend(self,records):self.pending.extend(records)

    def publish(self,records,last_sequence):
        """Publish IDs only after the encompassing durable commit succeeded."""
        first=last_sequence-len(records)+1
        for offset,record in enumerate(records):
            if self.kind is None or record.get("kind")==self.kind:self.indices.append(first+offset)
        self.pending.clear()
        # The final page can have grown since its previous read.
        self.pages.clear()

    def __len__(self):return len(self.indices)+len(self.pending)

    def _range(self,start,stop):
        if start>=stop:return []
        ids=self.indices[start:stop]
        if not ids:return []
        return [self._record(record) for record in self.history.event_range(ids[0],ids[-1],self.kind)]

    def __getitem__(self,index):
        if isinstance(index,slice):
            start,stop,step=index.indices(len(self))
            if step!=1:return [self[i] for i in range(start,stop,step)]
            persisted=len(self.indices)
            result=self._range(start,min(stop,persisted))
            if stop>persisted:result.extend(deepcopy(self.pending[max(0,start-persisted):stop-persisted]))
            return result
        if index<0:index+=len(self)
        if not 0<=index<len(self):raise IndexError(index)
        if index>=len(self.indices):return deepcopy(self.pending[index-len(self.indices)])
        page=index//128
        if page not in self.pages:
            self.pages[page]=self._range(page*128,min(len(self.indices),(page+1)*128))
            while len(self.pages)>4:self.pages.popitem(last=False)
        self.pages.move_to_end(page)
        return deepcopy(self.pages[page][index%128])

    def __iter__(self):
        for start in range(0,len(self.indices),128):
            yield from self._range(start,min(len(self.indices),start+128))
        yield from deepcopy(self.pending)

    def __deepcopy__(self,memo):return list(self)
    def to_dict(self):return list(self)
    def __eq__(self,other):return list(self)==list(other) if isinstance(other,(Sequence,list)) else False

    def observations_at(self,actor,when):
        """Retrieve authentic dated inputs without retaining all observations."""
        when=Fraction(str(when))
        records=self.history.decision_records_at(actor,when)
        records.extend(record for record in self.pending if str(record.get("actor"))==str(actor))
        return [record["observation"] for record in records
                if Fraction(str(record.get("observation",{}).get("time",0)))==when]


def attach_histories(simulation):
    simulation.events=LedgerRecords(simulation.history)
    simulation.decisions=LedgerRecords(simulation.history,"decision")
    simulation.random_draws=LedgerRecords(simulation.history,"random_draw")
