# Rebuilding the Three.js bundle

`vendor/three/three.module.min.js` is three@0.170.0 tree-shaken to the symbols `instrument.js` uses, plus
RoundedBoxGeometry from the examples. Source tree: `~/portfolio-tunnel/tunnel/vendor/three-0.170.0/` (MIT, licence in
`vendor/three/LICENSE`). Rebuild with esbuild 0.24.0 through npx (nothing installed into the repository):

```
T=~/portfolio-tunnel/tunnel/vendor/three-0.170.0
printf '%s\n' 'export { ACESFilmicToneMapping, AmbientLight, BackSide, BoxGeometry, BufferAttribute, BufferGeometry, CanvasTexture, Color, CylinderGeometry, DirectionalLight, DoubleSide, Euler, Group, HemisphereLight, LinearFilter, LinearMipmapLinearFilter, MathUtils, Matrix4, Mesh, MeshBasicMaterial, MeshPhysicalMaterial, MeshStandardMaterial, NoColorSpace, Object3D, PCFSoftShadowMap, PerspectiveCamera, PlaneGeometry, PMREMGenerator, Quaternion, RepeatWrapping, Scene, ShadowMaterial, SphereGeometry, SRGBColorSpace, Texture, Vector2, Vector3, WebGLRenderer } from "three";' \
  "export { RoundedBoxGeometry } from \"$T/examples/jsm/geometries/RoundedBoxGeometry.js\";" > /tmp/three-entry.js
npx -y esbuild@0.24.0 --bundle --minify --format=esm --alias:three=$T/build/three.module.js /tmp/three-entry.js --outfile=vendor/three/three.module.min.js
```

Result 2026-10-25: 478 KB raw, 124 KB gzip. Add a symbol to the export list when `instrument.js` needs one; a missing
symbol fails the module import and the page falls back to the poster (tests/portfolio-check.cjs section 8 and
gl-loss.cjs cover that failure).
