#!/usr/bin/env python3

import os
import sys
import enum

import logging

from custom_pysmiles import read_smiles
from custom_pysmiles.smiles_helper import (add_explicit_hydrogens, remove_explicit_hydrogens)

import networkx as nx
from networkx.algorithms import isomorphism as nxisomorphism

from rdkit import Chem

from pyvis.network import Network

#logging.basicConfig(format='%(asctime)s:%(levelname)s:%(message)s', level=logging.INFO)
logging.basicConfig(format='%(levelname)s:\t%(message)s', level=logging.INFO)

NO_MAP_DEFAULT_KEY = -1

mappedsmiles = sys.argv[1]
outputgml = sys.argv[2] 

map_hydrogens = False
if len(sys.argv) == 4:
    map_hydrogens = str(sys.argv[3])
    
# generate Folder with all molecules as single graphs
path = os.getcwd()
newpath = 'Molecule_Graphs' 
if not os.path.exists(newpath):
    os.makedirs(newpath)

## ========== DEF BLOCK

@enum.unique
class TransitionType(enum.IntEnum):
    """Possible SMILES token types"""
    NO_TRANSITION = 0
    SYMMETRY = 1
    REACTION = 2
    HYDROGEN_GROUP = 3
    HYDROGEN_REACTION = 4    
    HYDROGEN_FREE = 5

def hasPath(G, s, t, edge_type):
    if s == t:
        return True

    visited = set()
    visited.add(s)
    stack = [(s, iter(G[s]))]
    while stack:
        parent, children = stack[-1]

        for child in children:
            if child not in visited and G.edges[parent, child]['transition'] == edge_type:
                if child == t:
                    return True
                visited.add(child)
                stack.append((child, iter(G[child])))
        stack.pop()
    return False

def findHydrogenGroups(mol, mapped_hydrogens, mapped_atoms):

    inv_mapped_atom = {v: k for k, v in mapped_atoms.items()}    

    for n in mol.nodes():
        if mol.nodes[n].get('element', '') == 'H':
            class_id = NO_MAP_DEFAULT_KEY
            for neighbor in mol[n]:
                if neighbor in inv_mapped_atom:
                    class_id = inv_mapped_atom[neighbor]
            mapped_hydrogens.setdefault(class_id, []).append(n)

def findIsomorphATNStructure(ATN, mol):

    em = nxisomorphism.categorical_edge_match(['order'],[0])
    nm = nxisomorphism.categorical_node_match(['element','hcount', 'charge'],['', 0, 0])
    undi_ATN = ATN.to_undirected()
    GM = nxisomorphism.GraphMatcher(undi_ATN, mol, node_match=nm, edge_match=em)
    result_iso = nx.is_isomorphic(undi_ATN,mol, node_match=nm, edge_match=em)
    mapping_ATN_to_mol = GM.mapping
    #mapping_ATN_to_mol = GM.match()
    #mapping_ATN_to_mol = nx.vf2pp_isomorphism(undi_ATN,mol, node_label='element')
    print(result_iso)
    # print(list(mapping_ATN_to_mol))
    return result_iso, mapping_ATN_to_mol

def addAutomorphisms(mol, limit_to_orbits=True):
    em = nxisomorphism.categorical_edge_match(['order'],[0])
    nm = nxisomorphism.categorical_node_match(['element', 'hcount', 'charge'],['', 0, 0])
    GM = nxisomorphism.GraphMatcher(mol, mol, node_match=nm, edge_match=em)

    permutation_lists = list(GM.isomorphisms_iter())

    if limit_to_orbits:
        blockset = set()
        for node in mol.nodes():
            if node in blockset:
                continue
            for isomorphism in permutation_lists:
                if node != isomorphism[node]:
                   mol.add_edge(node, isomorphism[node])
                   mol.edges[node, isomorphism[node]]['transition'] = TransitionType.SYMMETRY
                   mol.edges[node, isomorphism[node]]['order'] = 0
                   blockset.add(isomorphism[node])
    else:
        for isomorphism in permutation_lists:
            for i in isomorphism:
                if i != isomorphism[i] and not mol.has_edge(i, isomorphism[i]):
                    mol.add_edge(i, isomorphism[i])
                    mol.edges[i, isomorphism[i]]['transition'] = TransitionType.SYMMETRY
                    mol.edges[i, isomorphism[i]]['order'] = 0

    
def parseXDuct(name, smiles, compound_to_subgraph, compoundId_to_compound, ATN, mapped_atoms, side, mapped_hydrogens = {}, explicit_hydrogens=False):

    logging.debug("Parse " + name + " : " + smiles)
    
    # rename molecules of highly conzentrations
    if side == 'left' and name in highmol_list:
        name = name + '_in'
    if side == 'right' and name in highmol_list:
        name = name + '_out'
            
    fixed_smiles = Chem.MolToSmiles(Chem.MolFromSmiles(smiles), allHsExplicit=True, canonical=False)
    mol = read_smiles( fixed_smiles ) # read smile
    # RXNMApper does not create valid H mappings, remove them all
    for n in mol.nodes():
        if mol.nodes[n].get('element', '') == 'H' and 'class' in mol.nodes[n]:
            del mol.nodes[n]['class']
    remove_explicit_hydrogens(mol)

    if name in compound_to_subgraph:

        logging.debug("Use Existing " + name)

        if explicit_hydrogens:
            add_explicit_hydrogens(mol)

        # we already added this compound to the network
        compound_subgraph = ATN.subgraph(compound_to_subgraph[name])
        has_isomorph_subgraph, mapping_ATN_to_mol = findIsomorphATNStructure(compound_subgraph, mol)
        print(has_isomorph_subgraph)
        if has_isomorph_subgraph:
            print('LOOP')
            print(mapping_ATN_to_mol)
            for atn_node in list(mapping_ATN_to_mol):
                print('MAPPING ATN')
                print(mapping_ATN_to_mol)
                if 'class' in mol.nodes[mapping_ATN_to_mol[atn_node]]:
                    mapped_atoms[ mol.nodes[mapping_ATN_to_mol[atn_node]]['class'] ] = atn_node
                    print('NEW MAPPING')
                    print(mapped_atoms)
        else:
            logging.error("Compound Naming Error: " + name + " : " + smiles)

        if explicit_hydrogens:
            logging.debug("Find Hydrogen Partners")
            findHydrogenGroups(compound_subgraph, mapped_hydrogens, mapped_atoms)

    else:

        logging.debug("Add New Compound "+ name)

        # this is definitely new
        nextCId = len(compound_to_subgraph)
        compoundId_to_compound[nextCId] = (name, fixed_smiles)

        rename = {node : str(nextCId)+'_'+str(node) for node in mol.nodes()} # rename all nodes so that we cannot have collisions in the ATN
        nx.relabel_nodes(mol, rename, copy=False)

        addAutomorphisms(mol)

        if explicit_hydrogens:
            add_explicit_hydrogens(mol, str(nextCId)+"_")

        for n in mol.nodes():
            mol.nodes[n]['compound_id'] = nextCId
            mol.nodes[n]['compound_name'] = name

        for e in mol.edges():
            if 'transition' not in mol.edges[e]:
                mol.edges[e]['transition'] = TransitionType.NO_TRANSITION

        ATN.add_nodes_from(mol.nodes(data=True))
        ATN.add_edges_from(mol.edges(data=True),arrows="no")

        for mol_node, data in mol.nodes(data=True):
            if 'class' in data:
                mapped_atoms[data['class']] = mol_node
                del mol.nodes[mol_node]['class']
            compound_to_subgraph.setdefault(name, []).append(mol_node)

        if explicit_hydrogens:
            logging.debug("Find Hydrogen Partners")
            findHydrogenGroups(mol, mapped_hydrogens, mapped_atoms)
            
        # save single molecule graph 
        #print(mol.nodes())
        newMol = mol.copy()
        for n in mol.nodes():
            newMol.nodes[n]['label'] = mol.nodes[n]['element'] + '(' + n + ')'
            if mol.nodes[n]['element'] == 'C':
                newMol.nodes[n]['color'] = "black"
            if mol.nodes[n]['element'] == 'O':
                newMol.nodes[n]['color'] = "red"    
            if mol.nodes[n]['element'] == 'C':
                newMol.nodes[n]['color'] = "black"
            if mol.nodes[n]['element'] == 'S':
                newMol.nodes[n]['color'] = "yellow"
        for e in mol.edges():
            newMol.edges[e]['label'] = str(mol.edges[e]['order'])
            newMol.edges[e]['color'] = "black"

        net = Network('1000px', '1000px')
        net.from_nx(newMol)
        with open(newpath + '/' + name + '.html', "w+") as out:
            out.write(net.generate_html())

        
# ======== MAIN

# reading in the list of highly concentrated molecules 
with open ( 'metanetx/list_highlyConcMol.txt' , 'r') as highmol_file:
       highmol = highmol_file.readlines() 
highmol_list = [s.strip() for s in highmol]

# first an intermediary with bonding and transition edges that is trimmed afterwards
ATN=nx.DiGraph()
compound_to_subgraph = {}
compoundId_to_compound = {}

reactions = []

# load all SMILES from txt files
with open( mappedsmiles , 'r') as smiles_file:
  while True:    
    #meta_line = smiles_file.readline()
    name_line = smiles_file.readline()
    mapped_smiles_line = smiles_file.readline()
    if not name_line or not  mapped_smiles_line:
       break;

    smiles_str = mapped_smiles_line.strip().replace("@", '').replace("/", '')
    names_str = name_line.strip()
    names_list = names_str.split(', Bigg ID:')
    names_str = names_list[0]
    reverse_list = names_list[1].split('Reversible: ')
    reverse_list_cut = reverse_list[1].split(' Samples:')
    reverse_line = reverse_list_cut[0]

    #meta_line = meta_line.strip().split()[5]
    #filename = ''.join(letter for letter in name_line if letter.isalnum())
    logging.info("Next Reaction ==============")
    logging.info(names_str)
    logging.info(mapped_smiles_line.strip())
    
    reactions.append( (names_str, smiles_str) )

    # create left and right list with the smiles
    smiles_sides = smiles_str.split('>>')
    smiles_left = smiles_sides[0].split('.')
    smiles_right = smiles_sides[1].split('.')
    
    # create left and right list with the metabolite names
    names_sides = names_str.split('=')
    names_left = list(map(str.strip, names_sides[0].split(' + ')))
    names_right = list(map(str.strip, names_sides[1].split(' + ')))

    # we have compartment change reactions that are not interesting for the ATN 
    if set(names_left) == set(names_right):
        continue

    logging.debug("Parse Educts")
    mapped_educt_atoms = {}
    mapped_educt_hydrogens = {}
    for name, smiles in zip(names_left, smiles_left):
        parseXDuct(name, smiles, compound_to_subgraph, compoundId_to_compound, ATN, mapped_educt_atoms, 'left', mapped_educt_hydrogens, map_hydrogens)

    logging.debug("Parse Products")
    mapped_product_atoms = {}
    mapped_product_hydrogens = {}
    for name, smiles in zip(names_right, smiles_right):
        print(name)
        parseXDuct(name, smiles, compound_to_subgraph, compoundId_to_compound, ATN, mapped_product_atoms, 'right', mapped_product_hydrogens, map_hydrogens)

    #if map_hydrogens:

        logging.debug("Map Hydrogens")

        trans_H_node = "react_"+str(len(reactions)-1)+"_free_H"

        key_set_educt  = set(mapped_educt_hydrogens.keys())
        key_set_product  = set(mapped_product_hydrogens.keys())
        key_set_all = key_set_educt.union(key_set_product)

        for key in key_set_all:

            hydro_count_educts = 0
            if key in key_set_educt:
                hydro_count_educts = len(mapped_educt_hydrogens[key])
            hydro_count_products = 0
            if key in key_set_product:
                hydro_count_products = len(mapped_product_hydrogens[key])

            if key == NO_MAP_DEFAULT_KEY or not hydro_count_educts == hydro_count_products:
                if not ATN.has_node(trans_H_node):
                    ATN.add_node(trans_H_node)
                    ATN.nodes[trans_H_node]['element'] = 'H'
                    
                if hydro_count_educts > hydro_count_products or (key == NO_MAP_DEFAULT_KEY and hydro_count_educts > 0):
                    for n in mapped_educt_hydrogens[key]:
                        ATN.add_edge(n, trans_H_node)
                        ATN.edges[n, trans_H_node]['transition'] = TransitionType.HYDROGEN_FREE
                        ATN.edges[n, trans_H_node]['reaction_id'] = str(len(reactions)-1)
                        ATN.edges[n, trans_H_node]['moving_atom'] = hydro_count_educts - hydro_count_products
                if hydro_count_educts < hydro_count_products or (key == NO_MAP_DEFAULT_KEY and hydro_count_products > 0):
                    for n in mapped_product_hydrogens[key]:
                        ATN.add_edge(trans_H_node, n)
                        ATN.edges[trans_H_node, n]['transition'] = TransitionType.HYDROGEN_FREE
                        ATN.edges[trans_H_node, n]['reaction_id'] = str(len(reactions)-1)
                        ATN.edges[n, trans_H_node]['moving_atom'] = hydro_count_products - hydro_count_educts

            # we always need to add in the real H transitions
            if key == NO_MAP_DEFAULT_KEY or hydro_count_educts == 0 or hydro_count_products == 0:
                continue
 
            rep_atom_educt = mapped_educt_hydrogens[key][0]
            rep_atom_product = mapped_product_hydrogens[key][0]
            if ATN.has_edge(rep_atom_educt,rep_atom_product):
                ATN.edges[rep_atom_educt,rep_atom_product]['reaction_id'] += ","+str(len(reactions)-1)
            else:
                ATN.add_edge(rep_atom_educt,rep_atom_product)
                ATN.edges[rep_atom_educt,rep_atom_product]['transition'] = TransitionType.HYDROGEN_REACTION
                ATN.edges[rep_atom_educt,rep_atom_product]['reaction_id'] = str(len(reactions)-1)

            for atom in mapped_educt_hydrogens[key][1:]: # all in group need to be connected
                if not hasPath(ATN, rep_atom_educt, atom, TransitionType.HYDROGEN_GROUP):
                    ATN.add_edge(rep_atom_educt, atom)
                    ATN.edges[rep_atom_educt, atom]['transition'] = TransitionType.HYDROGEN_GROUP

            for atom in mapped_product_hydrogens[key][1:]: # all in group need to be connected
                if not hasPath(ATN, rep_atom_product, atom, TransitionType.HYDROGEN_GROUP):
                    ATN.add_edge(rep_atom_product, atom)
                    ATN.edges[rep_atom_product, atom]['transition'] = TransitionType.HYDROGEN_GROUP
  
    for c in mapped_educt_atoms:
        print(mapped_educt_atoms)
        print(c)
        print(mapped_product_atoms)
        n1 = mapped_educt_atoms[c]
        n2 = mapped_product_atoms[c]

        if ATN.nodes[n1]['compound_id'] == ATN.nodes[n2]['compound_id']:
             continue # skip all self maps

        if ATN.has_edge(n1,n2):
            if reverse_line == 'false':
                ATN.edges[n1, n2]['reaction_id'] += str(len(reactions)-1)
            else:
                ATN.edges[n1, n2]['reaction_id'] += str(len(reactions)-1)
                ATN.edges[n2, n1]['reaction_id'] += str(len(reactions)-1)
        else:
            if reverse_line == 'true': #reverse RXNs
                if ATN.nodes[n2]['compound_name'].endswith('_in') or ATN.nodes[n2]['compound_name'].endswith('_out') or ATN.nodes[n1]['compound_name'].endswith('_in') or ATN.nodes[n1]['compound_name'].endswith('_out'):
                    ATN.add_edge(n1, n2)
                    ATN.edges[n1, n2]['transition'] = TransitionType.REACTION
                    ATN.edges[n1, n2]['reaction_id'] = str(len(reactions)-1)                
                else: 
                    ATN.add_edge(n1, n2)
                    ATN.edges[n1, n2]['transition'] = TransitionType.REACTION
                    ATN.edges[n1, n2]['reaction_id'] = str(len(reactions)-1) 
                    
                    ATN.add_edge(n2, n1)
                    ATN.edges[n2, n1]['transition'] = TransitionType.REACTION
                    ATN.edges[n2, n1]['reaction_id'] = str(len(reactions)-1) 
            else: # non reverse RXNs
                ATN.add_edge(n1, n2)
                ATN.edges[n1, n2]['transition'] = TransitionType.REACTION
                ATN.edges[n1, n2]['reaction_id'] = str(len(reactions)-1)
nx.write_gml(ATN, outputgml)

with open(outputgml+".ckey", 'w') as og:
  for key in sorted(compoundId_to_compound):
      print(key, compoundId_to_compound[key][0], compoundId_to_compound[key][1] ,sep='\t', file=og)



# DRAWING

draw = nx.DiGraph()
draw.add_nodes_from(ATN.nodes())
draw.add_edges_from(ATN.edges(data=True))


for n in ATN.nodes():
    draw.nodes[n]['label'] = ATN.nodes[n]['element']
    if 'hcount' in ATN.nodes[n]:
        draw.nodes[n]['label'] += str(ATN.nodes[n]['hcount'])+'H'
    draw.nodes[n]['color'] = "black"

for e in ATN.edges():
    if ATN.edges[e]['transition'] == TransitionType.SYMMETRY:
        draw.edges[e]['color'] = "green"
    elif ATN.edges[e]['transition'] == TransitionType.REACTION:
        draw.edges[e]['color'] = "red"
    elif ATN.edges[e]['transition'] == TransitionType.HYDROGEN_GROUP or ATN.edges[e]['transition'] == TransitionType.HYDROGEN_REACTION:
        draw.edges[e]['color'] = "LightSkyBlue"
    elif ATN.edges[e]['transition'] == TransitionType.HYDROGEN_FREE:
        draw.edges[e]['color'] = "DarkBlue"
    else:
        draw.edges[e]['label'] = str(ATN.edges[e]['order'])
        draw.edges[e]['color'] = "black"

nt = Network('1000px', '1000px', directed=True)
nt.show_buttons()
nt.from_nx(draw)
nt.show('nx2.html')
