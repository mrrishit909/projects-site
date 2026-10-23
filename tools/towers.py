# Blender 4.5: the home page hero. A daylight field of bar-chart towers in the site palette; the camera flies down the
# corridor and ends face to face with the butter tower, whose colour the first Selected Work screen picks up.
# usage: Blender -b --factory-startup -P tools/towers.py -- <out_prefix> <w> <h> <frames>   (frames 1 = the opening still)
import bpy, sys, math, random
from mathutils import Vector

a = sys.argv[sys.argv.index('--') + 1:]
out, W, H, NF = a[0], int(a[1]), int(a[2]), int(a[3])
portrait = H > W
random.seed(11)

sc = bpy.context.scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)

r = sc.render
r.engine = 'BLENDER_EEVEE_NEXT'
r.resolution_x, r.resolution_y, r.resolution_percentage = W, H, 100
r.image_settings.file_format = 'PNG'
r.image_settings.color_mode = 'RGB'
sc.view_settings.view_transform = 'Standard'
sc.view_settings.look = 'None'
sc.view_settings.exposure = -0.15
ee = sc.eevee
ee.taa_render_samples = 64
ee.use_shadows = True
ee.use_raytracing = True
ee.ray_tracing_options.resolution_scale = '1'
ee.fast_gi_method = 'GLOBAL_ILLUMINATION'


def srgb(h):
    c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def mat(name, hexc, rough=0.42, coat=0.25):
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes['Principled BSDF']
    b.inputs['Base Color'].default_value = (*srgb(hexc), 1)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Coat Weight'].default_value = coat
    b.inputs['Coat Roughness'].default_value = 0.25
    return m


# world: clear sky, pale blue overhead to warm cream at the horizon (camera rays); a soft sky light for the scene
w = bpy.data.worlds.new('w'); sc.world = w; w.use_nodes = True
nt = w.node_tree; n = nt.nodes; L = nt.links
bg = n['Background']
tc = n.new('ShaderNodeTexCoord'); sep = n.new('ShaderNodeSeparateXYZ'); ramp = n.new('ShaderNodeValToRGB')
L.new(tc.outputs['Generated'], sep.inputs[0]); L.new(sep.outputs['Z'], ramp.inputs[0])
cr = ramp.color_ramp
cr.elements[0].position = 0.0; cr.elements[0].color = (*srgb('#FFF1DC'), 1)
cr.elements[1].position = 0.32; cr.elements[1].color = (*srgb('#7FBFFF'), 1)
e = cr.elements.new(0.07); e.color = (*srgb('#CFE7FF'), 1)
L.new(ramp.outputs[0], bg.inputs['Color'])
bg.inputs['Strength'].default_value = 1.0
lp = n.new('ShaderNodeLightPath'); amb = n.new('ShaderNodeBackground')
amb.inputs['Color'].default_value = (*srgb('#BFDDFF'), 1); amb.inputs['Strength'].default_value = 0.9
mix = n.new('ShaderNodeMixShader')
L.new(lp.outputs['Is Camera Ray'], mix.inputs[0]); L.new(amb.outputs[0], mix.inputs[1]); L.new(bg.outputs[0], mix.inputs[2])
L.new(mix.outputs[0], n['World Output'].inputs['Surface'])

# sun: from behind the camera on the left, so the faces we fly toward are lit and shadows run away down the corridor
bpy.ops.object.light_add(type='SUN', rotation=(math.radians(52), 0, math.radians(-38)))
sun = bpy.context.object; sun.data.energy = 4.2; sun.data.color = srgb('#FFF3E2'); sun.data.angle = math.radians(1.5)

# ground: warm paper with a faint grid (perspective and detail for the lower frame)
bpy.ops.mesh.primitive_plane_add(size=1200, location=(0, 200, 0))
g = bpy.context.object
gm = bpy.data.materials.new('ground'); gm.use_nodes = True
gn = gm.node_tree.nodes; gl = gm.node_tree.links
gb = gn['Principled BSDF']; gb.inputs['Roughness'].default_value = 0.8
gtc = gn.new('ShaderNodeTexCoord'); gsep = gn.new('ShaderNodeSeparateXYZ')
gl.new(gtc.outputs['Object'], gsep.inputs[0])
def gridline(axis):
    m1 = gn.new('ShaderNodeMath'); m1.operation = 'PINGPONG'; m1.inputs[1].default_value = 2.0
    gl.new(gsep.outputs[axis], m1.inputs[0])
    m2 = gn.new('ShaderNodeMath'); m2.operation = 'LESS_THAN'; m2.inputs[1].default_value = 0.06
    gl.new(m1.outputs[0], m2.inputs[0]); return m2
gx, gy = gridline('X'), gridline('Y')
gmax = gn.new('ShaderNodeMath'); gmax.operation = 'MAXIMUM'
gl.new(gx.outputs[0], gmax.inputs[0]); gl.new(gy.outputs[0], gmax.inputs[1])
gmix = gn.new('ShaderNodeMix'); gmix.data_type = 'RGBA'
gmix.inputs['A'].default_value = (*srgb('#F6EBD8'), 1); gmix.inputs['B'].default_value = (*srgb('#E7D6BC'), 1)
gl.new(gmax.outputs[0], gmix.inputs['Factor']); gl.new(gmix.outputs['Result'], gb.inputs['Base Color'])
g.data.materials.append(gm)

PAL = ['#FF7759', '#9BD3FF', '#CDC6FF', '#BDEBC8', '#FFF7EA', '#FF7759', '#CDC6FF', '#9BD3FF']
mats = {h: mat('t' + h, h) for h in set(PAL)}
butter = mat('butter', '#FFD84D', 0.38, 0.3)


def tower(x, y, h, wd, dp, m):
    bpy.ops.mesh.primitive_cube_add(location=(x, y, h / 2))
    o = bpy.context.object; o.scale = (wd / 2, dp / 2, h / 2)
    bpy.ops.object.transform_apply(scale=True)
    o.data.materials.append(m)
    bev = o.modifiers.new('b', 'BEVEL'); bev.width = 0.35; bev.segments = 4
    bpy.ops.object.shade_smooth_by_angle()
    return o


# rows of bars either side of the corridor, rising toward the horizon like a chart
for i in range(16):
    y = 12 + i * 8
    for side in (-1, 1):
        x = side * (11 + random.uniform(0, 3) + i * 0.35)
        h = 4 + i * 1.2 + random.uniform(-2, 7)
        tower(x, y, h, random.uniform(3.2, 5), random.uniform(3.2, 5), mats[random.choice(PAL)])
        if random.random() < 0.6:
            tower(x + side * random.uniform(6, 10), y + random.uniform(-2, 2), h * random.uniform(0.7, 1.5),
                  random.uniform(3, 5.5), random.uniform(3, 5), mats[random.choice(PAL)])
# the hero bar: wide and tall, closing the corridor
END_Y = 160
tower(0, END_Y, 70, 16, 10, butter)

bpy.ops.object.camera_add()
cam = bpy.context.object; sc.camera = cam
cam.data.lens = 26 if portrait else 24
cam.data.clip_end = 1500


def place(t):
    # t 0..1: from the corridor mouth to a few metres from the butter tower's face
    y = -8 + t * (END_Y - 5 - 4 - (-8))
    z = 4.2 + t * 4.0
    cam.location = (0.0, y, z)
    look = Vector((0.0, y + 60, (16 if portrait else 10) * (1 - t) + z * t))
    cam.rotation_euler = (look - cam.location).to_track_quat('-Z', 'Y').to_euler()


for f in range(NF):
    t = 0.0 if NF == 1 else f / (NF - 1)
    place(t * t * (3 - 2 * t))
    r.filepath = out if NF == 1 else f"{out}{f:03d}"
    bpy.ops.render.render(write_still=True)
