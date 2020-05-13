"""
A protein structure prediction data set that includes sidechain information.
A direct extension of ProteinNet by Mohammed AlQuraishi.

"""
import argparse
import os
import re

import prody as pr
from tqdm import tqdm
from multiprocessing import Pool, cpu_count

from sidechainnet.utils.alignment import can_be_directly_merged, expand_data_with_mask

pr.confProDy(verbosity="none")

from sidechainnet.download_and_parse import download_sidechain_data, load_data, save_data
from sidechainnet.utils.proteinnet import parse_raw_proteinnet
from sidechainnet.utils.alignment import init_aligner
from sidechainnet.utils.structure import NUM_PREDICTED_COORDS


def combine(pn_entry, sc_entry, aligner, pnid):
    """ Supplements one entry in ProteinNet with sidechain information.

    Args:
        aligner: A sequence aligner with desired settings.
            See utils.alignment.init_aligner()
        pn_entry: A dictionary describing a single ProteinNet protein. Contains
            sequence, coordinates, PSSMs, secondary structure.
        sc_entry: A dictionary describing the sidechain information for the
            same protein. Contains sequence, coordinates, and angles.

    Returns:
        A dictionary that has unified the two sets of information.
    """
    if "secondary" in pn_entry:
        print("WARNING: secondary structure information is not yet supported. "
              "As of May 2020, it is not included in ProteinNet.")

    can_be_merged, mask, alignment, warning = can_be_directly_merged(aligner,
                                                            pn_entry["primary"],
                                                            sc_entry,
                                                            # sc_entry["seq"],
                                                            pn_entry["mask"],
                                                                     pnid)
    new_entry = {}

    if alignment:
        # Create new SidechainNet entry containing all information
        new_entry["seq"] = seq
        new_entry["evo"] = pn_entry["evolutionary"]

        # We may need to add padding where specified by the mask
        # new_entry["ang"] = expand_data_with_mask(sc_entry["ang"], mask)
        # new_entry["crd"] = expand_data_with_mask(sc_entry["crd"], mask)
        new_entry["msk"] = mask

        l = len(seq)
        for k, v in new_entry.items():
            if k == "crd":
                assert len(v) // NUM_PREDICTED_COORDS == l, f"{k} does not have correct length {l} (is {len(v)//NUM_PREDICTED_COORDS})."
            else:
                assert len(v) == l, f"{k} does not have correct length {l} (is {len(v)})."


    return new_entry, warning


def combine_datasets(proteinnet_out, sc_data, training_set):
    """Adds sidechain information to ProteinNet to create SidechainNet.

    Args:
        proteinnet_out: Location of preprocessed ProteinNet data
        sc_data: Sidechain data dictionary with keys being ProteinNet IDs
        training_set: Which training set thinning to use (i.e. 30, 50,... 100)

    Returns:
        SidechainNet as a dictionary mapping ProteinNet IDs to all data relevant
        for sidechain prediction.
    """
    print("Preparing to merge ProteinNet data with downloaded sidechain data.")
    pn_files = [os.path.join(proteinnet_out, f"training_{training_set}.pt"),
                os.path.join(proteinnet_out, f"validation.pt"),
                os.path.join(proteinnet_out, f"testing.pt")]

    pn_data = {}
    for f in pn_files:
        d = load_data(f)
        pn_data.update(d)
    del d

    # For debugging errors
    error_file = "/Users/jonathanking/Downloads/errorssidechain/COMBINED_1ALN_MISMATCH.txt"
    with open(error_file, "r") as f:
        error_ids = f.read().splitlines(keepends=False)

    errors = {"failed": [],
              "single alignment, mask mismatch": [],
              "multiple alignments, mask mismatch": [],
              "multiple alignments, mask mismatch, many alignments": [],
              "multiple alignments, found matching mask": [],
              "multiple alignments, found matching mask, many alignments": []}

    # with Pool(cpu_count()) as p:
    #     tuples = (get_tuple(pn_data, sc_data, pnid) for pnid in error_ids)
    #     results_warnings = list(tqdm(p.imap(combine_wrapper, tuples), total=len(error_ids), dynamic_ncols=True))

    aligner = init_aligner()
    for pnid in tqdm(error_ids, dynamic_ncols=True):
    # for (combined_result, warning), pnid in zip(results_warnings, sc_data.keys()):
        combined_result, warning = combine(pn_data[pnid], sc_data[pnid], aligner, pnid)
        if combined_result:
            pn_data[pnid] = combined_result
        else:
            del pn_data[pnid]
        if warning:
            errors[warning].append(pnid)

    # Record ProteinNet IDs that could not be combined or exhibited warnings
    with open("errors/COMBINED_ERRORS.txt", "w") as f:
        for failed_id in errors["failed"]:
            f.write(f"{failed_id}\n")
    with open("errors/COMBINED_1ALN_MISMATCH.txt", "w") as f:
        for failed_id in errors["single alignment, mask mismatch"]:
            f.write(f"{failed_id}\n")
    with open("errors/COMBINED_M-ALN_MISMATCH.txt", "w") as f:
        for failed_id in errors["multiple alignments, mask mismatch"]:
            f.write(f"{failed_id}\n")
    # with open("errors/COMBINED_M-ALN_MATCH.txt", "w") as f:
    #     for failed_id in errors["multiple alignments, found matching mask"]:
    #         f.write(f"{failed_id}\n")
    with open("errors/COMBINED_M-ALN_MISMATCH_MANY.txt", "w") as f:
        for failed_id in errors["multiple alignments, mask mismatch, many alignments"]:
            f.write(f"{failed_id}\n")
    # with open("errors/COMBINED_M-ALN_MATCH_MANY.txt", "w") as f:
    #     for failed_id in errors["multiple alignments, found matching mask, many alignments"]:
    #         f.write(f"{failed_id}\n")

    print(f"Finished unifying sidechain information with ProteinNet data.\n"
          f"{len(errors['failed'])} IDs failed to combine successfully.")
    return pn_data

def get_tuple(pndata, scdata, pnid):
    return pndata[pnid], scdata[pnid]

def combine_wrapper(pndata_scdata):
    pn_data, sc_data = pndata_scdata
    aligner = init_aligner()
    return combine(pn_data, sc_data, aligner)


def main():
    # First, create PyTorch versions of  raw proteinnet files for convenience
    pnids = parse_raw_proteinnet(args.proteinnet_in, args.proteinnet_out,
                                 args.training_set)

    # Using the ProteinNet IDs as a guide, download the relevant sidechain data
    # sc_data, sc_filename = download_sidechain_data(pnids, args.sidechainnet_out,
    #                                                args.casp_version,
    #                                                args.training_set,
    #                                                args.limit,
    #                                                args.proteinnet_in)

    # For debugging errors
    sc_data = load_data("../data/sidechainnet/seq-only_casp12_100.pt")

    # Finally, unify the sidechain data with ProteinNet
    sidechainnet = combine_datasets(args.proteinnet_out, sc_data,
                                    args.training_set)

    save_data(sidechainnet, os.path.join(args.sidechainnet_out,
                                         f"sidechainnet_{args.casp_version}"
                                         f"_{args.training_set}.pt"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Constructs SidechainNet.")
    parser.add_argument('proteinnet_in', type=str,
                        help='Path to ProteinNet raw records directory.')
    parser.add_argument('--proteinnet_out', '-po', type=str,
                        help='Where to save parsed, raw ProteinNet.',
                        default="../data/proteinnet/")
    parser.add_argument('--sidechainnet_out', '-so', type=str,
                        help='Where to save SidechainNet.',
                        default="../data/sidechainnet/")
    parser.add_argument('-l', '--limit', type=int, default=None,
                        help='Limit size of training set for debugging.')
    parser.add_argument("--pdb_dir", default=os.path.expanduser("~/pdb/"),
                        type=str,
                        help="Location to download PDB files for ProDy.")
    parser.add_argument('--training_set', type=int, default=100,
                        help='Which \'thinning\' of the ProteinNet training '
                        'set to parse. {30,50,70,90,95,100}. Default 100.')
    args = parser.parse_args()

    match = re.search(r"casp\d+", args.proteinnet_in, re.IGNORECASE)
    if not match:
        raise argparse.ArgumentError("The input_dir does not contain 'caspX'. "
                                     "Please ensure the raw files are enclosed "
                                     "in a path that contains the CASP version"
                                     " i.e. 'casp12'.")
    args.casp_version = match.group(0)

    main()
