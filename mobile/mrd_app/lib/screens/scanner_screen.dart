import 'package:flutter/material.dart';
import 'package:mobile_scanner/mobile_scanner.dart';
import '../services/api_service.dart';
import '../config/theme.dart';

class ScannerScreen extends StatefulWidget {
  const ScannerScreen({super.key});
  @override
  State<ScannerScreen> createState() => _ScannerScreenState();
}

class _ScannerScreenState extends State<ScannerScreen> {
  final _ctrl = MobileScannerController(
    detectionSpeed: DetectionSpeed.noDuplicates,
    facing: CameraFacing.back,
  );
  bool _scanning = true;
  String? _lastCode;

  void _onDetect(BarcodeCapture capture) async {
    if (!_scanning) return;
    final barcode = capture.barcodes.firstOrNull;
    if (barcode?.rawValue == null) return;
    final code = barcode!.rawValue!;
    setState(() { _scanning = false; _lastCode = code; });

    // Buscar en API
    try {
      final r = await ApiService.instance.get('/scan/buscar', params: {'q': code});
      if (!mounted) return;
      final data = r.data;
      if (data['found'] == true) {
        _showResult(data);
      } else {
        _showNotFound(code);
      }
    } catch (e) {
      if (mounted) _showError(code);
    }
  }

  void _showResult(Map<String, dynamic> data) {
    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: MrdTheme.surfaceDark,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(20))),
      builder: (_) => _ScanResultSheet(data: data, onClose: _resumeScan),
    );
  }

  void _showNotFound(String code) {
    showDialog(
      context: context,
      builder: (_) => AlertDialog(
        backgroundColor: MrdTheme.cardDark,
        title: const Text('No encontrado'),
        content: Text('Código: $code\nNo se encontró en el inventario.'),
        actions: [
          TextButton(onPressed: () { Navigator.pop(context); _resumeScan(); },
            child: const Text('Cerrar')),
          ElevatedButton(
            onPressed: () { Navigator.pop(context); _resumeScan(); },
            child: const Text('Crear incidencia'),
          ),
        ],
      ),
    );
  }

  void _showError(String code) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text('Error al buscar: $code'), backgroundColor: MrdTheme.danger),
    );
    _resumeScan();
  }

  void _resumeScan() => setState(() => _scanning = true);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Escáner QR / Código de barras'),
        actions: [
          IconButton(
            icon: const Icon(Icons.flash_on),
            onPressed: () => _ctrl.toggleTorch(),
          ),
          IconButton(
            icon: const Icon(Icons.flip_camera_ios),
            onPressed: () => _ctrl.switchCamera(),
          ),
        ],
      ),
      body: Stack(
        children: [
          MobileScanner(controller: _ctrl, onDetect: _onDetect),
          // Marco de escaneo
          Center(
            child: Container(
              width: 260, height: 260,
              decoration: BoxDecoration(
                border: Border.all(color: MrdTheme.secondary, width: 3),
                borderRadius: BorderRadius.circular(16),
              ),
            ),
          ),
          // Instrucciones
          Positioned(
            bottom: 40,
            left: 0, right: 0,
            child: Center(
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 10),
                decoration: BoxDecoration(
                  color: Colors.black54,
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Text(
                  _scanning ? 'Apunta al código QR o de barras' : 'Procesando...',
                  style: const TextStyle(color: Colors.white, fontSize: 14),
                ),
              ),
            ),
          ),
        ],
      ),
    );
  }

  @override
  void dispose() {
    _ctrl.dispose();
    super.dispose();
  }
}

class _ScanResultSheet extends StatelessWidget {
  final Map<String, dynamic> data;
  final VoidCallback onClose;
  const _ScanResultSheet({required this.data, required this.onClose});

  @override
  Widget build(BuildContext context) {
    final herramienta = data['herramienta'] as Map<String, dynamic>?;
    final nombre = herramienta?['nombre'] ?? data['nombre'] ?? '—';
    final codigo = herramienta?['codigo'] ?? data['codigo'] ?? '—';
    final estado = herramienta?['estado'] ?? '—';
    return Padding(
      padding: const EdgeInsets.all(24),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.check_circle, color: MrdTheme.success, size: 28),
              const SizedBox(width: 10),
              const Text('Encontrado', style: TextStyle(
                fontSize: 18, fontWeight: FontWeight.w600, color: MrdTheme.success)),
              const Spacer(),
              IconButton(icon: const Icon(Icons.close), onPressed: () {
                Navigator.pop(context); onClose();
              }),
            ],
          ),
          const Divider(height: 24),
          Text(nombre, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
          const SizedBox(height: 4),
          Text('Código: $codigo', style: const TextStyle(color: Colors.white54)),
          const SizedBox(height: 8),
          Chip(
            label: Text(estado.toString().toUpperCase(),
              style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
            backgroundColor: MrdTheme.success.withOpacity(0.2),
            side: const BorderSide(color: MrdTheme.success),
          ),
          const SizedBox(height: 20),
          Row(
            children: [
              Expanded(
                child: ElevatedButton.icon(
                  onPressed: () {
                    Navigator.pop(context);
                    Navigator.pushNamed(context, '/herramientas/detalle',
                      arguments: herramienta);
                    onClose();
                  },
                  icon: const Icon(Icons.visibility),
                  label: const Text('Ver detalle'),
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: () { Navigator.pop(context); onClose(); },
                  icon: const Icon(Icons.qr_code_scanner),
                  label: const Text('Seguir escaneando'),
                  style: OutlinedButton.styleFrom(foregroundColor: MrdTheme.accent),
                ),
              ),
            ],
          ),
          const SizedBox(height: 16),
        ],
      ),
    );
  }
}
