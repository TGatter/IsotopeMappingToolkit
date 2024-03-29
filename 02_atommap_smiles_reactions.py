#!/usr/bin/env python3

from rxnmapper import RXNMapper
from rdkit import Chem
import sys
import itertools
from transformers import logging

logging.set_verbosity_error()

reactions = sys.argv[1]
outputmapped = sys.argv[2] 

def isa_group_separator(line):
    return line=='\n'

with open(reactions, mode='r') as rf:
 with open(outputmapped, 'w') as omf:
   for key,group in itertools.groupby(rf,isa_group_separator):
      #print(key, list(group))
      if key:
         continue

      id_line, ec_line, name_reaction, smiles_reaction = map(str.strip, list(group))

      try:
          rxn_mapper = RXNMapper()
          results = rxn_mapper.get_attention_guided_atom_maps([smiles_reaction], canonicalize_rxns=False)   

          print(id_line.strip(), file=omf)
          print(name_reaction, file=omf)
          print(results[0]['mapped_rxn'], file=omf)
      except RuntimeError:
         print("skipped reaction of length", len(smiles_reaction), file=sys.stderr)
         print(id_line, file=sys.stderr)
