package com.preludeofme.squishmate.render

import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RadialGradient
import android.graphics.RectF
import android.graphics.Shader
import com.preludeofme.squishmate.anim.Pose
import kotlin.math.cos
import kotlin.math.sin

/**
 * Kotlin/Canvas port of `ui/blob_renderer.py` — draws the alien blob
 * procedurally, no image assets, from the [Pose] produced each frame by
 * `anim/PetAnimator.kt`. See docs/android_plan.md §5.2/§7 (Phase 2).
 *
 * Mapping from Qt to `android.graphics`:
 *   `QPainterPath.cubicTo`        -> `Path.cubicTo` (same absolute-control-point convention)
 *   `QPainter.translate/scale/rotate` -> `Canvas.translate/scale/rotate` (same units, degrees)
 *   `QRadialGradient`/`QLinearGradient` -> set as a `Paint.shader`
 *   `QColor.lighter(f)/.darker(f)` -> [lighterColor]/[darkerColor] (HSV-value
 *     scaling approximation of Qt's actual algorithm — visual parity, not
 *     bit-exact; acceptable for a "port", see the plan's Phase 2 scope)
 *
 * This is NOT golden-tested (unlike `PetAnimator`) — it's a paint routine,
 * not deterministic state math, so the useful regression test is "renders
 * without throwing" plus eyeballing on a real device, matching how the
 * desktop Bézier shape-preset work was verified (see active-context.md).
 */

enum class AntennaStyle { SINGLE, TWIN, CURLY, NONE }

data class ShapePreset(
    val wScale: Double,
    val hScale: Double,
    val topTaper: Double,
    val armReach: Double,
    val antenna: AntennaStyle,
    val horns: Boolean,
)

val SHAPE_PRESETS: Map<String, ShapePreset> = mapOf(
    "round" to ShapePreset(1.00, 1.00, 1.00, 1.00, AntennaStyle.SINGLE, false),
    "tall" to ShapePreset(0.82, 1.22, 0.85, 0.85, AntennaStyle.SINGLE, false),
    "wide" to ShapePreset(1.22, 0.82, 1.05, 1.15, AntennaStyle.TWIN, false),
    "teardrop" to ShapePreset(0.92, 1.14, 0.55, 0.90, AntennaStyle.CURLY, false),
    "chubby" to ShapePreset(1.18, 0.92, 1.10, 0.60, AntennaStyle.NONE, true),
    "horned" to ShapePreset(1.00, 1.02, 1.00, 1.00, AntennaStyle.SINGLE, true),
)
const val DEFAULT_SHAPE = "round"
val PATTERNS = listOf("plain", "spots", "stripes", "stars")
const val DEFAULT_BODY_COLOR = "#C9A5F0"

private fun colorOf(hex: String): Int = Color.parseColor(hex)

private fun lighterColor(color: Int, factor: Int): Int {
    val hsv = FloatArray(3)
    Color.colorToHSV(color, hsv)
    hsv[2] = (hsv[2] * factor / 100f).coerceIn(0f, 1f)
    return Color.HSVToColor(Color.alpha(color), hsv)
}

private fun darkerColor(color: Int, factor: Int): Int {
    val hsv = FloatArray(3)
    Color.colorToHSV(color, hsv)
    hsv[2] = (hsv[2] * 100f / factor).coerceIn(0f, 1f)
    return Color.HSVToColor(Color.alpha(color), hsv)
}

private fun withAlpha(color: Int, alpha: Int): Int =
    Color.argb(alpha.coerceIn(0, 255), Color.red(color), Color.green(color), Color.blue(color))

class BlobRenderer(
    private val winW: Float,
    private val winH: Float,
    color: String = DEFAULT_BODY_COLOR,
    pattern: String = "plain",
    shape: String = DEFAULT_SHAPE,
) {
    companion object {
        const val BASE_W = 44.0
        const val BASE_H = 42.0
        private val EYE = colorOf("#2D1B36")
        private val BLUSH = colorOf("#FF9EC4")
        private val SHADOW = Color.rgb(30, 20, 50)
    }

    private val cx: Float = winW / 2f
    private val ground: Float = winH - 20f

    var bodyMid: Int = 0; private set
    var bodyLight: Int = 0; private set
    var bodyDark: Int = 0; private set
    var bodyEdge: Int = 0; private set

    var pattern: String = "plain"
        private set
    var shape: String = DEFAULT_SHAPE
        private set
    private var shapePreset: ShapePreset = SHAPE_PRESETS.getValue(DEFAULT_SHAPE)

    var bodyW: Double = BASE_W; private set
    var bodyH: Double = BASE_H; private set

    private val fillPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val strokePaint = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
    private val textPaint = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = 32f
        isFakeBoldText = true
    }

    init {
        applyColor(color)
        applyPattern(pattern)
        applyShape(shape)
    }

    fun applyColor(hex: String) {
        val c = try { colorOf(hex) } catch (e: IllegalArgumentException) { return }
        bodyMid = c
        bodyLight = lighterColor(c, 132)
        bodyDark = darkerColor(c, 128)
        bodyEdge = darkerColor(c, 158)
    }

    fun applyPattern(p: String) {
        pattern = if (p in PATTERNS) p else "plain"
    }

    fun applyShape(s: String) {
        shape = if (SHAPE_PRESETS.containsKey(s)) s else DEFAULT_SHAPE
        shapePreset = SHAPE_PRESETS.getValue(shape)
        bodyW = BASE_W * shapePreset.wScale
        bodyH = BASE_H * shapePreset.hScale
    }

    // ------------------------------------------------------------------ paths
    private fun bodyPath(pose: Pose): Path {
        val w = bodyW; val h = bodyH
        val top = shapePreset.topTaper
        val reach = shapePreset.armReach
        val t = pose.t
        val w1 = sin(t * 1.7) * 1.6
        val w2 = sin(t * 2.3 + 1.0) * 1.4
        val w3 = sin(t * 1.3 + 2.1) * 1.8
        val w4 = sin(t * 2.9 + 0.5) * 1.2
        val armR = h * 0.10 + pose.armR
        val armL = h * 0.10 + pose.armL
        val a1 = 1.0 + 0.02 * reach
        val a2 = 1.0 + 0.24 * reach
        val a3 = 1.0 + 0.30 * reach
        val a4 = 1.0 + 0.34 * reach
        val a5 = 1.0 + 0.12 * reach

        val p = Path()
        p.moveTo(0f, -h.toFloat())
        p.cubicTo(
            (w * 0.55 * top).toFloat(), (-h + w2).toFloat(),
            (w * 0.98 * top + w1).toFloat(), (-h * 0.55).toFloat(),
            (w * 0.94 * top).toFloat(), (-h * 0.12).toFloat(),
        )
        p.cubicTo(
            (w * a1).toFloat(), 0f,
            (w * a2).toFloat(), (armR - 10).toFloat(),
            (w * a3).toFloat(), armR.toFloat(),
        )
        p.cubicTo(
            (w * a4).toFloat(), (armR + 7).toFloat(),
            (w * a5).toFloat(), (armR + 12).toFloat(),
            (w * 0.92).toFloat(), (h * 0.40).toFloat(),
        )
        p.cubicTo(
            (w * 0.86).toFloat(), (h * 0.78).toFloat(),
            (w * 0.55).toFloat(), (h * 0.98).toFloat(),
            (w * 0.20).toFloat(), (h + w3 * 0.4).toFloat(),
        )
        p.cubicTo(
            (w * 0.07).toFloat(), (h + 1.5 + w4 * 0.5).toFloat(),
            (-w * 0.07).toFloat(), (h + 1.5 - w4 * 0.5).toFloat(),
            (-w * 0.20).toFloat(), (h + w4 * 0.4).toFloat(),
        )
        p.cubicTo(
            (-w * 0.55).toFloat(), (h * 0.98).toFloat(),
            (-w * 0.86).toFloat(), (h * 0.78).toFloat(),
            (-w * 0.92).toFloat(), (h * 0.40).toFloat(),
        )
        p.cubicTo(
            (-w * a5).toFloat(), (armL + 12).toFloat(),
            (-w * a4).toFloat(), (armL + 7).toFloat(),
            (-w * a3).toFloat(), armL.toFloat(),
        )
        p.cubicTo(
            (-w * a2).toFloat(), 0f,
            (-w * a1).toFloat(), 0f,
            (-w * 0.94 * top).toFloat(), (-h * 0.12).toFloat(),
        )
        p.cubicTo(
            (-w * 0.98 * top - w1).toFloat(), (-h * 0.55).toFloat(),
            (-w * 0.55 * top).toFloat(), (-h + w2).toFloat(),
            0f, (-h).toFloat(),
        )
        p.close()
        return p
    }

    // ------------------------------------------------------------------- draw
    fun draw(canvas: Canvas, pose: Pose) {
        drawShadow(canvas, pose)

        canvas.save()
        canvas.translate(cx, (ground + pose.offsetY).toFloat())
        canvas.scale(pose.scaleX.toFloat(), pose.scaleY.toFloat())
        canvas.translate(0f, -bodyH.toFloat())
        if (pose.bodyRotation != 0.0) {
            canvas.rotate(pose.bodyRotation.toFloat())
        }

        drawAntenna(canvas, pose)
        if (shapePreset.horns) drawHorns(canvas)
        val body = bodyPath(pose)
        drawBody(canvas, body, pose)
        drawFace(canvas, pose)
        canvas.restore()

        if (pose.sleeping) drawZzz(canvas, pose)
    }

    private fun drawShadow(canvas: Canvas, pose: Pose) {
        val lift = 1.0 / (1.0 + kotlin.math.abs(pose.offsetY) / 30.0)
        val rx = (40.0 * (bodyW / BASE_W) * pose.scaleX * (0.6 + 0.4 * lift)).toFloat()
        fillPaint.style = Paint.Style.FILL
        fillPaint.shader = null
        fillPaint.color = withAlpha(SHADOW, (60 * lift).toInt())
        canvas.drawOval(
            RectF(cx - rx, ground + 7 - 7f, cx + rx, ground + 7 + 7f), fillPaint,
        )
    }

    private fun drawAntenna(canvas: Canvas, pose: Pose) {
        when (shapePreset.antenna) {
            AntennaStyle.NONE -> return
            AntennaStyle.TWIN -> {
                drawAntennaStalk(canvas, pose, xOff = -7.0, swayScale = 0.75, height = 21.0, penWidth = 3.6f)
                drawAntennaStalk(canvas, pose, xOff = 7.0, swayScale = 0.75, height = 21.0, penWidth = 3.6f)
            }
            AntennaStyle.CURLY -> drawAntennaCurly(canvas, pose)
            AntennaStyle.SINGLE -> drawAntennaStalk(canvas, pose)
        }
    }

    private fun drawAntennaStalk(
        canvas: Canvas, pose: Pose, xOff: Double = 0.0, swayScale: Double = 1.0,
        height: Double = 30.0, penWidth: Float = 4.5f,
    ) {
        val h = bodyH
        val sway = pose.antennaSway * swayScale
        val baseX = xOff.toFloat(); val baseY = (-h + 4).toFloat()
        val tipX = (xOff + sway).toFloat(); val tipY = (-h - height).toFloat()
        val path = Path()
        path.moveTo(baseX, baseY)
        path.cubicTo(
            (xOff + sway * 0.15).toFloat(), (-h - height * 0.33).toFloat(),
            (xOff + sway * 0.55).toFloat(), (-h - height * 0.70).toFloat(),
            tipX, tipY,
        )
        strokePaint.color = bodyEdge
        strokePaint.strokeWidth = penWidth
        strokePaint.strokeCap = Paint.Cap.ROUND
        strokePaint.shader = null
        canvas.drawPath(path, strokePaint)

        val bulbShader = RadialGradient(
            tipX - 1.5f, tipY - 1.5f, 7f,
            intArrayOf(colorOf("#F5EBFF"), bodyMid, bodyEdge),
            floatArrayOf(0.0f, 0.55f, 1.0f),
            Shader.TileMode.CLAMP,
        )
        fillPaint.shader = bulbShader
        fillPaint.style = Paint.Style.FILL
        canvas.drawOval(RectF(tipX - 5f, tipY - 5f, tipX + 5f, tipY + 5f), fillPaint)
        fillPaint.shader = null
        strokePaint.color = bodyEdge
        strokePaint.strokeWidth = 1.2f
        canvas.drawOval(RectF(tipX - 5f, tipY - 5f, tipX + 5f, tipY + 5f), strokePaint)
    }

    private fun drawAntennaCurly(canvas: Canvas, pose: Pose) {
        val h = bodyH
        val sway = pose.antennaSway
        val baseX = 0f; val baseY = (-h + 4).toFloat()
        val midX = (sway * 0.4).toFloat(); val midY = (-h - 16).toFloat()
        val path = Path()
        path.moveTo(baseX, baseY)
        path.cubicTo(
            (sway * 0.15).toFloat(), (-h - 8).toFloat(),
            (sway * 0.4).toFloat(), (-h - 14).toFloat(),
            midX, midY,
        )
        path.cubicTo(midX + 7f, midY - 4f, midX + 7f, midY + 6f, midX, midY + 6f)
        path.cubicTo(midX - 5f, midY + 6f, midX - 3f, midY - 2f, midX + 1f, midY - 1f)
        strokePaint.color = bodyEdge
        strokePaint.strokeWidth = 4.0f
        strokePaint.strokeCap = Paint.Cap.ROUND
        strokePaint.shader = null
        canvas.drawPath(path, strokePaint)
    }

    private fun drawHorns(canvas: Canvas) {
        val h = bodyH; val w = bodyW
        for (side in intArrayOf(-1, 1)) {
            val baseX = (side * w * 0.32).toFloat(); val baseY = (-h * 0.88).toFloat()
            val tipX = (side * w * 0.40).toFloat(); val tipY = (-h * 1.22).toFloat()
            val path = Path()
            path.moveTo(baseX - side * 3.5f, baseY)
            path.lineTo(tipX, tipY)
            path.lineTo(baseX + side * 3.5f, baseY)
            path.close()
            strokePaint.color = bodyEdge
            strokePaint.strokeWidth = 1.4f
            fillPaint.shader = null
            fillPaint.color = bodyMid
            canvas.drawPath(path, fillPaint)
            canvas.drawPath(path, strokePaint)
        }
    }

    private fun drawBody(canvas: Canvas, body: Path, pose: Pose) {
        val w = bodyW; val h = bodyH
        val grad = RadialGradient(
            (-w * 0.35).toFloat(), (-h * 0.45).toFloat(), (w * 2.1).toFloat(),
            intArrayOf(bodyLight, bodyMid, bodyDark),
            floatArrayOf(0.0f, 0.55f, 1.0f),
            Shader.TileMode.CLAMP,
        )
        fillPaint.shader = grad
        fillPaint.style = Paint.Style.FILL
        canvas.drawPath(body, fillPaint)
        fillPaint.shader = null
        strokePaint.color = bodyEdge
        strokePaint.strokeWidth = 2.6f
        canvas.drawPath(body, strokePaint)

        canvas.save()
        canvas.clipPath(body)

        // Darker translucent lower-body wash. A linear gradient can't be
        // expressed as a single flat fill the way Qt's QLinearGradient
        // rect fill was — approximate the top-to-bottom fade with a
        // gradient-shaded rect (visual parity, not exact).
        val shadeShader = android.graphics.LinearGradient(
            0f, (h * 0.1).toFloat(), 0f, h.toFloat(),
            Color.argb(0, 126, 93, 192), Color.argb(90, 126, 93, 192),
            Shader.TileMode.CLAMP,
        )
        fillPaint.shader = shadeShader
        canvas.drawRect(
            RectF((-w * 1.4).toFloat(), (h * 0.1).toFloat(), (w * 1.4).toFloat(), (h + 4).toFloat()),
            fillPaint,
        )
        fillPaint.shader = null

        val t = pose.t
        val bubbles = arrayOf(
            Triple(-w * 0.45, h * 0.45, 4.0),
            Triple(w * 0.30, h * 0.60, 3.0),
            Triple(w * 0.55, h * 0.25, 2.4),
        )
        bubbles.forEachIndexed { i, (bx, by, r) ->
            val dx = sin(t * 0.7 + i * 2.1) * 2.0
            val dy = cos(t * 0.5 + i * 1.3) * 2.0
            fillPaint.color = Color.argb(42, 255, 255, 255)
            canvas.drawOval(
                RectF(
                    (bx + dx - r).toFloat(), (by + dy - r).toFloat(),
                    (bx + dx + r).toFloat(), (by + dy + r).toFloat(),
                ),
                fillPaint,
            )
        }

        fillPaint.color = Color.argb(70, 255, 255, 255)
        val hlRx = (w * 0.30).toFloat(); val hlRy = (h * 0.22).toFloat()
        val hlCx = (-w * 0.34).toFloat(); val hlCy = (-h * 0.42).toFloat()
        canvas.drawOval(RectF(hlCx - hlRx, hlCy - hlRy, hlCx + hlRx, hlCy + hlRy), fillPaint)

        drawPattern(canvas)
        canvas.restore()
    }

    private fun drawPattern(canvas: Canvas) {
        if (pattern == "plain") return
        val w = bodyW; val h = bodyH
        val shade = withAlpha(bodyDark, 100)

        when (pattern) {
            "spots" -> {
                fillPaint.color = shade
                val spots = arrayOf(
                    Triple(-w * 0.35, h * 0.15, 4.5), Triple(w * 0.15, h * 0.55, 3.6),
                    Triple(w * 0.42, -h * 0.05, 3.0), Triple(-w * 0.05, h * 0.75, 3.2),
                    Triple(-w * 0.50, -h * 0.10, 2.6),
                )
                spots.forEach { (sx, sy, r) ->
                    canvas.drawOval(
                        RectF((sx - r).toFloat(), (sy - r).toFloat(), (sx + r).toFloat(), (sy + r).toFloat()),
                        fillPaint,
                    )
                }
            }
            "stripes" -> {
                fillPaint.color = shade
                doubleArrayOf(-h * 0.35, -h * 0.02, h * 0.32, h * 0.68).forEach { sy ->
                    val rect = RectF(
                        (-w * 1.15).toFloat(), sy.toFloat(),
                        (w * 1.15).toFloat(), (sy + 5.0).toFloat(),
                    )
                    canvas.drawRoundRect(rect, 2.5f, 2.5f, fillPaint)
                }
            }
            "stars" -> {
                val sparkle = Color.argb(210, 255, 255, 255)
                val stars = arrayOf(
                    Triple(-w * 0.40, -h * 0.10, 2.4), Triple(w * 0.30, h * 0.30, 2.0),
                    Triple(w * 0.05, -h * 0.38, 1.8), Triple(-w * 0.10, h * 0.62, 2.0),
                    Triple(w * 0.48, -h * 0.02, 1.6),
                )
                stars.forEach { (sx, sy, r) -> drawStar(canvas, sx, sy, r, sparkle) }
            }
        }
    }

    private fun drawStar(canvas: Canvas, cx: Double, cy: Double, r: Double, color: Int) {
        val path = Path()
        for (i in 0 until 5) {
            val angle = Math.PI / 2 + i * (2 * Math.PI / 5)
            val ox = (cx + r * cos(angle)).toFloat()
            val oy = (cy - r * sin(angle)).toFloat()
            if (i == 0) path.moveTo(ox, oy) else path.lineTo(ox, oy)
            val innerAngle = angle + Math.PI / 5
            path.lineTo(
                (cx + r * 0.45 * cos(innerAngle)).toFloat(),
                (cy - r * 0.45 * sin(innerAngle)).toFloat(),
            )
        }
        path.close()
        fillPaint.shader = null
        fillPaint.color = color
        canvas.drawPath(path, fillPaint)
    }

    private fun drawFace(canvas: Canvas, pose: Pose) {
        val eyeY = -8.0
        val eyeRx = 8.0 * pose.eyeScale
        val eyeRy = 10.5 * pose.eyeScale * maxOf(pose.eyeOpen, 0.0)
        val px = pose.pupilDx * 3.0
        val py = pose.pupilDy * 2.0

        for (side in intArrayOf(-1, 1)) {
            val ex = side * 16.0 + px
            if (pose.eyeOpen < 0.18) {
                val path = Path()
                path.moveTo((ex - eyeRx).toFloat(), (eyeY + 2).toFloat())
                path.quadTo(ex.toFloat(), (eyeY + 6.5).toFloat(), (ex + eyeRx).toFloat(), (eyeY + 2).toFloat())
                strokePaint.color = EYE
                strokePaint.strokeWidth = 2.4f
                strokePaint.strokeCap = Paint.Cap.ROUND
                canvas.drawPath(path, strokePaint)
                continue
            }
            fillPaint.shader = null
            fillPaint.color = EYE
            canvas.drawOval(
                RectF(
                    (ex - eyeRx).toFloat(), (eyeY + py - eyeRy).toFloat(),
                    (ex + eyeRx).toFloat(), (eyeY + py + eyeRy).toFloat(),
                ),
                fillPaint,
            )
            fillPaint.color = Color.argb(235, 255, 255, 255)
            val s1cx = ex - eyeRx * 0.32; val s1cy = eyeY + py - eyeRy * 0.35
            val s1rx = eyeRx * 0.34; val s1ry = eyeRy * 0.28
            canvas.drawOval(
                RectF((s1cx - s1rx).toFloat(), (s1cy - s1ry).toFloat(), (s1cx + s1rx).toFloat(), (s1cy + s1ry).toFloat()),
                fillPaint,
            )
            fillPaint.color = Color.argb(160, 255, 255, 255)
            val s2cx = ex + eyeRx * 0.30; val s2cy = eyeY + py + eyeRy * 0.30
            val s2rx = eyeRx * 0.16; val s2ry = eyeRy * 0.13
            canvas.drawOval(
                RectF((s2cx - s2rx).toFloat(), (s2cy - s2ry).toFloat(), (s2cx + s2rx).toFloat(), (s2cy + s2ry).toFloat()),
                fillPaint,
            )
        }

        if (kotlin.math.abs(pose.brow) > 0.05) {
            strokePaint.color = EYE
            strokePaint.strokeWidth = 2.2f
            strokePaint.strokeCap = Paint.Cap.ROUND
            for (side in intArrayOf(-1, 1)) {
                val ex = side * 16.0 + px
                val innerX = ex - side * 6.0
                val outerX = ex + side * 6.0
                val baseY = eyeY - 12.0
                val innerY = baseY - 3.0 * pose.brow
                val outerY = baseY + 3.0 * pose.brow
                canvas.drawLine(outerX.toFloat(), outerY.toFloat(), innerX.toFloat(), innerY.toFloat(), strokePaint)
            }
        }

        if (pose.blush > 0) {
            fillPaint.shader = null
            fillPaint.color = withAlpha(BLUSH, (120 * pose.blush).toInt())
            for (side in intArrayOf(-1, 1)) {
                val bx = side * 27.0; val by = 3.0
                canvas.drawOval(
                    RectF((bx - 6.5).toFloat(), (by - 4.0).toFloat(), (bx + 6.5).toFloat(), (by + 4.0).toFloat()),
                    fillPaint,
                )
            }
        }

        if (pose.mouthOpen > 0.3) {
            strokePaint.color = EYE
            strokePaint.strokeWidth = 2.0f
            fillPaint.shader = null
            fillPaint.color = Color.rgb(90, 50, 110)
            val ry = 5.5 * pose.mouthOpen
            canvas.drawOval(RectF(-4.5f, (9.0 - ry).toFloat(), 4.5f, (9.0 + ry).toFloat()), fillPaint)
            canvas.drawOval(RectF(-4.5f, (9.0 - ry).toFloat(), 4.5f, (9.0 + ry).toFloat()), strokePaint)
        } else {
            val path = Path()
            path.moveTo(-7.0f, 8.0f)
            path.quadTo(0.0f, (8.0 + 9.0 * pose.mouth).toFloat(), 7.0f, 8.0f)
            strokePaint.color = EYE
            strokePaint.strokeWidth = 2.2f
            strokePaint.strokeCap = Paint.Cap.ROUND
            canvas.drawPath(path, strokePaint)
        }

        if (pose.foodVisual > 0.01) {
            val r = 4.5 * pose.foodVisual
            strokePaint.color = colorOf("#B87A2E")
            strokePaint.strokeWidth = 1.0f
            fillPaint.shader = null
            fillPaint.color = colorOf("#FFCB61")
            canvas.drawOval(RectF((9.0 - r).toFloat(), (13.0 - r).toFloat(), (9.0 + r).toFloat(), (13.0 + r).toFloat()), fillPaint)
            canvas.drawOval(RectF((9.0 - r).toFloat(), (13.0 - r).toFloat(), (9.0 + r).toFloat(), (13.0 + r).toFloat()), strokePaint)
        }
    }

    private fun drawZzz(canvas: Canvas, pose: Pose) {
        val pulse = (sin(pose.t * 1.6) + 1.0) / 2.0
        textPaint.color = withAlpha(bodyEdge, (120 + 100 * pulse).toInt())
        val baseX = cx + 34
        val baseY = ground - 2 * bodyH.toFloat() - 14
        canvas.drawText("z", baseX, (baseY + pulse * -3).toFloat(), textPaint)
        canvas.drawText("z", baseX + 10, (baseY - 12 + pulse * -4).toFloat(), textPaint)
    }
}
