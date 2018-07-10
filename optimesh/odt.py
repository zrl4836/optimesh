# -*- coding: utf-8 -*-
#
from __future__ import print_function

import numpy
import fastfunc

from meshplex import MeshTri

from .helpers import (
    runner,
    get_new_points_volume_averaged,
    get_new_points_count_averaged,
    energy,
    print_stats,
)


def fixed_point(*args, uniform_density=False, **kwargs):
    """Optimal Delaunay Triangulation.

    Long Chen, Michael Holst,
    Efficient mesh optimization schemes based on Optimal Delaunay
    Triangulations,
    Comput. Methods Appl. Mech. Engrg. 200 (2011) 967–984,
    <https://doi.org/10.1016/j.cma.2010.11.007>.

    Idea:
    Move interior mesh points into the weighted averages of the circumcenters
    of their adjacent cells. If a triangle cell switches orientation in the
    process, don't move quite so far.
    """
    compute_average = (
        get_new_points_volume_averaged
        if uniform_density
        else get_new_points_count_averaged
    )

    def get_new_points(mesh):
        # Get circumcenters everywhere except at cells adjacent to the boundary;
        # barycenters there.
        cc = mesh.get_cell_circumcenters()
        bc = mesh.get_cell_barycenters()
        # Find all cells with a boundary edge
        boundary_cell_ids = mesh.get_edges_cells()[1][:, 0]
        cc[boundary_cell_ids] = bc[boundary_cell_ids]
        return compute_average(mesh, cc)

    return runner(get_new_points, *args, **kwargs)


def nonlinear_optimization(
    X, cells, tol, max_num_steps, verbosity=1, step_filename_format=None
):
    """Optimal Delaunay Triangulation smoothing.

    This method minimizes the energy

        E = int_Omega |u_l(x) - u(x)| rho(x) dx

    where u(x) = ||x||^2, u_l is its piecewise linear nodal interpolation and
    rho is the density. Since u(x) is convex, u_l >= u everywhere and

        u_l(x) = sum_i phi_i(x) u(x_i)

    where phi_i is the hat function at x_i. With rho(x)=1, this gives

        E = int_Omega sum_i phi_i(x) u(x_i) - u(x)
          = 1/(d+1) sum_i ||x_i||^2 |omega_i| - int_Omega ||x||^2

    where d is the spatial dimension and omega_i is the star of x_i (the set of
    all simplices containing x_i).
    """
    import scipy.optimize

    # TODO remove this assertion and test
    # flat mesh
    assert X.shape[1] == 2

    mesh = MeshTri(X, cells, flat_cell_correction=None)

    if step_filename_format:
        mesh.save(
            step_filename_format.format(0),
            show_centroids=False,
            show_coedges=False,
            show_axes=False,
            nondelaunay_edge_color="k",
        )

    if verbosity > 0:
        print("Before:")
        extra_cols = ["energy: {:.5e}".format(energy(mesh))]
        print_stats(mesh, extra_cols=extra_cols)

    mesh.mark_boundary()

    def f(x):
        mesh.update_interior_node_coordinates(x.reshape(-1, 2))
        return energy(mesh, uniform_density=True)

    # TODO put f and jac together
    def jac(x):
        mesh.update_interior_node_coordinates(x.reshape(-1, 2))

        grad = numpy.zeros(mesh.node_coords.shape)
        cc = mesh.get_cell_circumcenters()
        for mcn in mesh.cells["nodes"].T:
            fastfunc.add.at(
                grad, mcn, ((mesh.node_coords[mcn] - cc).T * mesh.cell_volumes).T
            )
        gdim = 2
        grad *= 2 / (gdim + 1)
        return grad[mesh.is_interior_node, :2].flatten()

    def flip_delaunay(x):
        flip_delaunay.step += 1
        # Flip the edges
        mesh.update_interior_node_coordinates(x.reshape(-1, 2))
        mesh.flip_until_delaunay()

        if step_filename_format:
            mesh.save(
                step_filename_format.format(flip_delaunay.step),
                show_centroids=False,
                show_coedges=False,
                show_axes=False,
                nondelaunay_edge_color="k",
            )
        if verbosity > 1:
            print("\nStep {}:".format(flip_delaunay.step))
            print_stats(mesh, extra_cols=["energy: {}".format(f(x))])

        # mesh.show()
        # exit(1)
        return

    flip_delaunay.step = 0

    x0 = X[mesh.is_interior_node, :2].flatten()

    out = scipy.optimize.minimize(
        f,
        x0,
        jac=jac,
        method="CG",
        # method='newton-cg',
        tol=tol,
        callback=flip_delaunay,
        options={"maxiter": max_num_steps},
    )
    # Don't assert out.success; max_num_steps may be reached, that's fine.

    # One last edge flip
    mesh.update_interior_node_coordinates(out.x.reshape(-1, 2))
    mesh.flip_until_delaunay()

    if verbosity > 0:
        print("\nFinal ({} steps):".format(out.nit))
        extra_cols = ["energy: {:.5e}".format(energy(mesh))]
        print_stats(mesh, extra_cols=extra_cols)
        print()

    return mesh.node_coords, mesh.cells["nodes"]
