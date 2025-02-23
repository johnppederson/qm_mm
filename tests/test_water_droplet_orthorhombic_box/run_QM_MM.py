from __future__ import print_function
import sys
sys.path.append('/home/mcdanielgroup/data/Jesse/QM_MM/lib/')
# append path to MM class library
sys.path.append('/home/mcdanielgroup/data/Jesse/Fixed_Voltage_OpenMM/lib/')
#********* import QMclass
from QM_classes import *
#********* import MMclass
from MM_classes import *

import numpy as np
# other stuff
import sys
from sys import stdout
from time import gmtime, strftime
from datetime import datetime
import argparse

parser = argparse.ArgumentParser()
parser.add_argument("--pdb", type=str, help="pdb file")
args = parser.parse_args()

# for electrode sheets, need to up recursion limit for residue atom matching...
sys.setrecursionlimit(2000)

# *********************************************************************
#                     Define QM region
#
#  1) QMatoms_list: These are atoms treated quantum mechanically 
#
#  2) QMregion_list: In addition to quantum mechanical atoms, this includes MM atoms that should be treated
#     with analytic Coulomb embedding in Psi4.  In general QMatoms_list should be a subset of QMregion_list.
#
#  3) MMatoms are everything else.  Any atoms not in QMregion_list will contribute to vext_tot computed by OpenMM
#
#  4) In, general, should use at least a 3-5 Angstrom buffer of atoms around QMatoms_list that is included in QMregion_list.
#     these MM atoms will have analytic electrostatic embedding within Psi4.  The reason this is important is 2-fold.
#     First, even a small DFT quadrature grid will extend 3-4 Angstrom away from the nucleus.  This will overlap with
#     some atoms in the MM region, and so Coulomb interactions with these grid points will diverge.  Obviously this is not
#     a problem for analytic integrals, but is a problem for the numerical vext_tot, which may give 'infty' from Coulomb divergence
#     in OpenMM.
#     Second, this should significantly help errors due to interpolation from the PME_grid to the quadrature grid.  Without this buffer region,
#     interpolation errors will be significant, especially for nuclear energy contribution
#  
#

hartree_to_kjmol = 2625.4996
nm_to_bohr = 18.89726


# these are atom indices from input '*.pdb' file that define the atoms in the QM region
# remember, indexing starts at zero ...

# QM atoms only

QMatoms_list=(120, 121, 122)
# charge and spin
QMcharge=0
QMspin=1
#QMspin=2

# QM atoms and MM atoms with analytic Coulomb embedding
# we anticipate that we will eventually generate QMregion_list automatically
# from QMatoms_list using a cutoff distance

QMregion_list=(120, 121, 122)

# Make sure QMatoms_list is subset of QMregion_list
if not set(QMatoms_list).issubset(QMregion_list) :
   print(' QMatoms_list must be subset of QMregion_list !!')
   sys.exit()


# QMother is the difference between lists ..
QMother_list=np.setdiff1d( np.array( QMregion_list ) , np.array( QMatoms_list ) )
#**********************************************************************


DFT_functional='PBE'
pme_grid_size=500

# *********************************************************************
#                     Create MM system object
#**********************************************************************

# Initialize: Input list of pdb and xml files, and QMregion_list
MMsys=MM( pdb_list = [ args.pdb , ] , residue_xml_list = [ 'residues.xml' , ] , ff_xml_list = [ 'spce.xml', ] , QMregion_list = QMregion_list  )

# if periodic residue, call this
MMsys.set_periodic_residue(True)

# set PME parameters.  This is important for control of accuracy for vext interpolation to DFT quadrature
# choice of alpha:  For n=43 grid, 60 Angstrom box, OpenMM chooses alpha= 2.389328 nm^-1
MMsys.setPMEParameters( pme_alpha=2.5 , pme_grid_a=pme_grid_size , pme_grid_b=pme_grid_size , pme_grid_c=pme_grid_size ) # alpha, nx, ny, nz

#***********  Initialze OpenMM API's, this method creates simulation object
MMsys.set_platform('Reference')   # only 'Reference' platform is currently implemented!

# IMPORTANT: generate exclusions for SAPT-FF

#exclusions = electrode_sapt_generate_exclusions(MMsys.simmd, MMsys.system, MMsys.modeller.positions, cathode_name , anode_name)

# Umbrella potential on QM atoms
#MMsys.setumbrella( 'N2', 'grph', 'C100', 2000.0 , 0.4 )   # molecule1, molecule2, atom2,  k (kJ/mol/nm^2) , r0 nm


# *********************************************************************
#                     Create QM system object
#**********************************************************************

# Define QM region and Initialize QM class
# possible quadrature grids: see Psi4 manual
#quadrature_grid = ( 50 , 12 )  # spherical points, radial points
#quadrature_grid = ( 302 , 50 )  # spherical points, radial points
#quadrature_grid = ( 302 , 75 )  # spherical points, radial points
quadrature_grid = ( 2702 , 89 )  # spherical points, radial points

QMsys = QM( QMname = 'test' , basis = 'aug-cc-pvdz' , dft_spherical_points = quadrature_grid[0] , dft_radial_points = quadrature_grid[1] , scf_type = 'df' , qmmm='true' )

# get elements/charges of QM region atoms from MMsys ...
element_lists , charge_lists = MMsys.get_element_charge_for_atom_lists( [ QMatoms_list , QMother_list ] )
# Fill QM region with atoms.
QMsys.set_QM_region( element_lists , charge_lists , QMatoms_list, QMother_list )

#**********************************************************************
#                     QM/MM Simulation
#**********************************************************************

print( 'calculating energy, force, and vext...')
#******************* External potential on PME grid ******************
state = MMsys.simmd.context.getState(getEnergy=True,getForces=True,getVelocities=True,getPositions=True,getVext_grids=True, getPME_grid_positions=True)
print('done calculating energy, force, and vext')

# external potential on PME grid
vext_tot = state.getVext_grid()
# PME grid positions
PME_grid_positions = state.getPME_grid_positions()      

#** vext_tot from OpenMM is in kJ/mol/e  units, convert to Hartree for input to Psi4
vext_tot = np.array( vext_tot ) / hartree_to_kjmol
#** PME_grid_positions from OpenMM is in nanometers, convert to Bohr for input to Psi4
PME_grid_positions = np.array( PME_grid_positions ) * nm_to_bohr
#** box vectors in units of Bohr
box = get_box_vectors_Bohr( state , nm_to_bohr )

# Get QM positions from MMsystem and set them in QMsys object
positions_lists = MMsys.get_positions_for_atom_lists([ QMatoms_list , QMother_list ] )
QMsys.set_QM_positions( positions_lists )

# set geometry of QM region
QMsys.set_geometry( charge = QMcharge, spin = QMspin )


# QM calculation
#*********************************************************
#       2 ways to intepolate vext from PME grid to DFT quadrature.  These are controlled by input **kwarg to psi4.energy
#  ****** Method 1:  Input PME_grid_positions in real space, interpolate in real space *********
#        LIMITATIONS- a) this doesn't consider PBC, if any points in quadrature grid fall outside of principle simulation box, then interpolation will crash!
#                     b) this can't handle non-cubic (triclinic) boxes.  Use Method 2 if either a) or b) is a problem
# 2 options for scipy interpolation: set interpolation_method = "interpn" or "griddata".  "interpn" should be much faster and is for regularly spaced grids
#( QMsys.energy , QMsys.wfn ) = psi4.energy( DFT_functional , return_wfn=True , pme_grid_size=pme_grid_size , vexternal_grid=vext_tot , pmegrid_xyz = PME_grid_positions , interpolation_method="interpn" )
#
#  ******  Method 2:  Input box vectors, project DFT quadrature grid to PME grid, and interpolate on PME grid
#         this works with arbitrary triclinic boxes, and imposes PBC on DFT quadrature grid
( QMsys.energy , QMsys.wfn ) = psi4.energy( DFT_functional , return_wfn=True , pme_grid_size=pme_grid_size , vexternal_grid=vext_tot , box = box , interpolation_method="interpn" )

print( 'QM energy ' , QMsys.energy )

sys.exit()


