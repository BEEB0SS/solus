import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'

export interface BodyState {
  pos: number[]
  quat: number[]
  size?: number[]
  type?: string
}

export type SceneHandles = ReturnType<typeof createScene>

// ── Three.js scene management ────────────────────────────────────────

export function createBodyMesh(name: string, body: BodyState): THREE.Mesh {
  const sz = body.size || []
  let geo: THREE.BufferGeometry
  let mat: THREE.MeshStandardMaterial
  if (name === 'chassis') {
    geo = new THREE.BoxGeometry((sz[0] || 0.1) * 2, (sz[2] || 0.015) * 2, (sz[1] || 0.075) * 2)
    mat = new THREE.MeshStandardMaterial({ color: 0x3344aa })
  } else if (name.startsWith('wheel_')) {
    geo = new THREE.CylinderGeometry(sz[0] || 0.033, sz[0] || 0.033, (sz[1] || 0.013) * 2, 16)
    geo.rotateX(Math.PI / 2)
    mat = new THREE.MeshStandardMaterial({ color: 0x333333 })
  } else {
    geo = new THREE.BoxGeometry((sz[0] || 0.1) * 2, (sz[2] || 0.05) * 2, (sz[1] || 0.1) * 2)
    mat = new THREE.MeshStandardMaterial({ color: 0xcc3333, transparent: true, opacity: 0.8 })
  }
  return new THREE.Mesh(geo, mat)
}

export function createScene(container: HTMLDivElement) {
  const width = container.clientWidth
  const height = container.clientHeight || 400

  const scene = new THREE.Scene()
  scene.background = new THREE.Color(0x0a0a0f)

  const camera = new THREE.PerspectiveCamera(50, width / height, 0.01, 50)
  camera.position.set(0.3, 0.8, 0.8)
  camera.lookAt(0, 0, 0)

  const renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setSize(width, height)
  renderer.setPixelRatio(window.devicePixelRatio)
  container.appendChild(renderer.domElement)

  const controls = new OrbitControls(camera, renderer.domElement)
  controls.target.set(0, 0, 0)
  controls.enableDamping = true
  controls.dampingFactor = 0.1

  // Lights
  const dirLight = new THREE.DirectionalLight(0xffffff, 1.5)
  dirLight.position.set(2, 5, 3)
  scene.add(dirLight)
  scene.add(new THREE.AmbientLight(0x666680, 1.0))

  // Ground plane with grid — large enough that the car can't drive off it
  const groundGeo = new THREE.PlaneGeometry(40, 40)
  const groundMat = new THREE.MeshStandardMaterial({ color: 0x1a1a24, roughness: 0.9 })
  const ground = new THREE.Mesh(groundGeo, groundMat)
  ground.rotation.x = -Math.PI / 2
  ground.position.y = -0.001
  scene.add(ground)

  const grid = new THREE.GridHelper(40, 400, 0x2a2a3e, 0x222235)
  scene.add(grid)

  // Trail line
  const trailMat = new THREE.LineBasicMaterial({ color: 0x3b82f6, transparent: true, opacity: 0.6 })
  const trailGeo = new THREE.BufferGeometry()
  const trailPositions = new Float32Array(600 * 3) // max 600 points
  trailGeo.setAttribute('position', new THREE.BufferAttribute(trailPositions, 3))
  trailGeo.setDrawRange(0, 0)
  const trailLine = new THREE.Line(trailGeo, trailMat)
  scene.add(trailLine)

  // Ultrasonic beam
  const beamMat = new THREE.LineBasicMaterial({ color: 0x06b6d4, transparent: true, opacity: 0.5 })
  const beamGeo = new THREE.BufferGeometry()
  beamGeo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3))
  const beamLine = new THREE.Line(beamGeo, beamMat)
  scene.add(beamLine)

  return { scene, camera, renderer, controls, trailLine, trailGeo, trailPositions, beamLine, beamGeo }
}

export function applyMujocoTransform(mesh: THREE.Object3D, body: BodyState) {
  // MuJoCo: pos=[x,y,z] → Three.js: x=mj.x, y=mj.z, z=-mj.y (swap Y↔Z, negate)
  mesh.position.set(body.pos[0], body.pos[2], -body.pos[1])
  // MuJoCo quat: [w,x,y,z] → Three.js Quaternion(x,y,z,w) with axis swap
  mesh.quaternion.set(body.quat[1], body.quat[3], -body.quat[2], body.quat[0])
}

export const DEFAULT_BODIES: Record<string, BodyState> = {
  chassis: { pos: [0, 0, 0.049], quat: [1, 0, 0, 0], size: [0.1, 0.075, 0.015], type: 'box' },
  wheel_fl: { pos: [0.05, 0.08, 0.034], quat: [1, 0, 0, 0], size: [0.033, 0.013], type: 'cylinder' },
  wheel_fr: { pos: [0.05, -0.08, 0.034], quat: [1, 0, 0, 0], size: [0.033, 0.013], type: 'cylinder' },
  wheel_rl: { pos: [-0.05, 0.08, 0.034], quat: [1, 0, 0, 0], size: [0.033, 0.013], type: 'cylinder' },
  wheel_rr: { pos: [-0.05, -0.08, 0.034], quat: [1, 0, 0, 0], size: [0.033, 0.013], type: 'cylinder' },
  obstacle_1: { pos: [0.5, 0, 0.05], quat: [1, 0, 0, 0], size: [0.1, 0.15, 0.05], type: 'box' },
  obstacle_2: { pos: [-0.3, 0.4, 0.05], quat: [1, 0, 0, 0], size: [0.075, 0.075, 0.05], type: 'box' },
  obstacle_3: { pos: [0.1, -0.5, 0.03], quat: [1, 0, 0, 0], size: [0.15, 0.05, 0.03], type: 'box' },
  obstacle_4: { pos: [-0.5, -0.3, 0.05], quat: [1, 0, 0, 0], size: [0.05, 0.2, 0.05], type: 'box' },
}
