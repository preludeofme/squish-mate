package com.preludeofme.squishmate.anim

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.fail
import org.junit.Test
import kotlin.math.abs

/**
 * Golden test for [PetAnimator] — replays the EXACT SAME scripted trigger
 * sequence as `scripts/generate_animator_golden.py` (desktop repo) against
 * this Kotlin port and diffs every [Pose] field, per frame, against the
 * fixture that script generated. See docs/android_plan.md §5.2/§8.
 *
 * If this test fails after a deliberate change to `ui/pet_animator.py`,
 * regenerate the fixture with
 * `.venv/bin/python scripts/generate_animator_golden.py` from the desktop
 * repo root, port the equivalent change into [PetAnimator]/pose-shaping
 * functions here, and re-run.
 *
 * Tolerance is intentionally non-zero (not bit-exact): Python's libm and
 * the JVM's `Math` class can differ in the last ULP or two for
 * sin/cos/exp, and small per-frame differences would otherwise compound
 * over ~700 frames of iterative integration (antenna spring, position).
 * [EPS] is generous enough to catch real porting bugs (wrong constant,
 * swapped sign, missing branch) while tolerating floating-point noise.
 */
class PetAnimatorGoldenTest {

    private data class GoldenFrame(
        val t: Double, val scaleX: Double, val scaleY: Double, val offsetY: Double,
        val antennaSway: Double, val armL: Double, val armR: Double, val eyeOpen: Double,
        val eyeScale: Double, val pupilDx: Double, val pupilDy: Double, val mouth: Double,
        val mouthOpen: Double, val blush: Double, val brow: Double, val bodyRotation: Double,
        val foodVisual: Double, val sleeping: Boolean, val state: String,
    )

    private fun loadFixture(): Pair<Double, List<GoldenFrame>> {
        val stream = javaClass.classLoader?.getResourceAsStream("animator_golden.json")
            ?: throw IllegalStateException(
                "animator_golden.json fixture not found on test classpath — run " +
                    "scripts/generate_animator_golden.py from the desktop repo root " +
                    "and commit android/app/src/test/resources/animator_golden.json")
        val text = stream.bufferedReader().use { it.readText() }
        val root = JSONObject(text)
        val dt = root.getDouble("dt")
        val framesJson = root.getJSONArray("frames")
        val frames = (0 until framesJson.length()).map { i ->
            val f = framesJson.getJSONObject(i)
            GoldenFrame(
                t = f.getDouble("t"),
                scaleX = f.getDouble("scale_x"),
                scaleY = f.getDouble("scale_y"),
                offsetY = f.getDouble("offset_y"),
                antennaSway = f.getDouble("antenna_sway"),
                armL = f.getDouble("arm_l"),
                armR = f.getDouble("arm_r"),
                eyeOpen = f.getDouble("eye_open"),
                eyeScale = f.getDouble("eye_scale"),
                pupilDx = f.getDouble("pupil_dx"),
                pupilDy = f.getDouble("pupil_dy"),
                mouth = f.getDouble("mouth"),
                mouthOpen = f.getDouble("mouth_open"),
                blush = f.getDouble("blush"),
                brow = f.getDouble("brow"),
                bodyRotation = f.getDouble("body_rotation"),
                foodVisual = f.getDouble("food_visual"),
                sleeping = f.getBoolean("sleeping"),
                state = f.getString("state"),
            )
        }
        return Pair(dt, frames)
    }

    /** Mirrors `generate_animator_golden.py`'s `build_animator()` +
     * scripted sequence exactly (same order, same step counts). */
    private fun runScript(dt: Double): List<Pose> {
        val huge = Pair(1.0e6, 1.0e6)
        val anim = PetAnimator(
            80.0, 80.0,
            hopRange = huge, waveRange = huge, wanderRange = huge,
            sleepAfter = 1.0e6, actionRange = huge,
        )
        anim.nextBlink = 1.0e6

        val cursor = doubleArrayOf(250.0, 250.0)
        val screen = intArrayOf(0, 0, 1920, 1080)
        val poses = mutableListOf<Pose>()

        fun run(steps: Int) {
            repeat(steps) { poses.add(anim.update(dt, cursor, screen)) }
        }

        run(10)

        anim.triggerHop(force = true)
        run(45)

        anim.triggerWave(force = true)
        run(60)

        anim.triggerYawn(force = true)
        run(50)

        anim.triggerStretch(force = true)
        run(60)

        anim.triggerDance(force = true)
        run(85)

        anim.triggerSomersault(force = true)
        run(40)

        anim.triggerEat(force = true)
        run(65)

        anim.triggerGiggle(force = true)
        run(35)

        anim.triggerSleep(force = true)
        run(20)
        anim.wake()
        run(35)

        anim.startDrag()
        run(15)
        anim.endDrag()
        run(10)

        anim.targetX = anim.x + 400
        anim.targetY = anim.y
        anim.moving = true
        run(60)

        anim.setExpression(Emotion.HAPPY, duration = 2.0)
        run(70)
        anim.setExpression(Emotion.SCARED, duration = 1.5)
        run(50)

        return poses
    }

    @Test
    fun `Kotlin animator matches Python fixture frame-for-frame`() {
        val (dt, golden) = loadFixture()
        val actual = runScript(dt)

        assertEquals("frame count mismatch — script drifted out of sync with the fixture",
            golden.size, actual.size)

        val eps = EPS
        golden.forEachIndexed { i, g ->
            val a = actual[i]
            fun near(name: String, expected: Double, got: Double) {
                if (abs(expected - got) > eps) {
                    fail("frame $i field '$name' (state=${g.state}): " +
                        "expected=$expected actual=$got diff=${abs(expected - got)}")
                }
            }
            near("t", g.t, a.t)
            near("scale_x", g.scaleX, a.scaleX)
            near("scale_y", g.scaleY, a.scaleY)
            near("offset_y", g.offsetY, a.offsetY)
            near("antenna_sway", g.antennaSway, a.antennaSway)
            near("arm_l", g.armL, a.armL)
            near("arm_r", g.armR, a.armR)
            near("eye_open", g.eyeOpen, a.eyeOpen)
            near("eye_scale", g.eyeScale, a.eyeScale)
            near("pupil_dx", g.pupilDx, a.pupilDx)
            near("pupil_dy", g.pupilDy, a.pupilDy)
            near("mouth", g.mouth, a.mouth)
            near("mouth_open", g.mouthOpen, a.mouthOpen)
            near("blush", g.blush, a.blush)
            near("brow", g.brow, a.brow)
            near("body_rotation", g.bodyRotation, a.bodyRotation)
            near("food_visual", g.foodVisual, a.foodVisual)
            assertEquals("frame $i sleeping mismatch", g.sleeping, a.sleeping)
        }
    }

    companion object {
        private const val EPS = 0.02
    }
}
