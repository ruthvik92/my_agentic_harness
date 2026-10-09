import os
import subprocess
import tempfile
import uuid

from . import image_info, pdf_geometry, pdf_source, render_bounds, workspace_io

MAX_BYTES = 8 * 1024 * 1024


def render_pdf_region(args, root='/workspace'):
    pdf, page, region, dpi = render_bounds.validate_render_args(args)
    if region is None:
        raise ValueError('region is required')
    with pdf_source.snapshot_pdf(pdf, root) as (temp_pdf, source_hash):
        geometry = pdf_geometry.page_geometry(temp_pdf, page)
        x, y, W, H = render_bounds.crop_rectangle(geometry, region, dpi)
        with tempfile.TemporaryDirectory(dir='/tmp') as tmpdir:
            out_prefix = os.path.join(tmpdir, 'crop')
            env = {'LC_ALL': 'C', 'PATH': '/usr/local/bin:/usr/bin:/bin'}
            subprocess.run(
                ['pdftoppm', '-f', str(page), '-l', str(page), '-r', str(dpi),
                 '-singlefile', '-png', '-x', str(x), '-y', str(y),
                 '-W', str(W), '-H', str(H), temp_pdf, out_prefix],
                check=True, timeout=120, env=env,
            )
            with open(out_prefix + '.png', 'rb') as fh:
                data = fh.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError('rendered image exceeds size limit')
            meta = image_info.image_metadata(data)
            leaf = uuid.uuid4().hex + '.png'
            relative_path = 'scratch/images/' + leaf
            with workspace_io.parent_fd(relative_path, root=root, create=True) as (directory_fd, leaf_name):
                out_fd = os.open(leaf_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                                 0o600, dir_fd=directory_fd)
                with os.fdopen(out_fd, 'wb') as out:
                    out.write(data)
            return {
                'kind': 'image',
                'path': relative_path,
                **meta,
                'source': {
                    'pdf': pdf,
                    'sha256': source_hash,
                    'page': page,
                    'dpi': dpi,
                    'region': list(region),
                },
            }
