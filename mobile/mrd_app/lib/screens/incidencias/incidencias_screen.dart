import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';
import 'package:signature/signature.dart';
import 'dart:io';
import '../../services/api_service.dart';
import '../../services/local_database.dart';
import '../../models/models.dart';
import '../../config/theme.dart';

class IncidenciasScreen extends StatefulWidget {
  const IncidenciasScreen({super.key});
  @override
  State<IncidenciasScreen> createState() => _IncidenciasScreenState();
}

class _IncidenciasScreenState extends State<IncidenciasScreen> {
  List<Incidencia> _items = [];
  bool _loading = true;

  @override
  void initState() { super.initState(); _load(); }

  Future<void> _load() async {
    setState(() => _loading = true);
    try {
      final r = await ApiService.instance.get('/api/v1/incidencias');
      final list = (r.data['items'] as List?)?.map((j) => Incidencia.fromJson(j)).toList() ?? [];
      if (mounted) setState(() { _items = list; _loading = false; });
    } catch (_) {
      if (mounted) setState(() => _loading = false);
    }
  }

  Color _prioColor(String p) {
    switch(p) { case 'alta': return MrdTheme.danger; case 'media': return MrdTheme.warning; default: return MrdTheme.success; }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Incidencias'), actions: [
        IconButton(icon: const Icon(Icons.refresh), onPressed: _load),
      ]),
      body: _loading
        ? const Center(child: CircularProgressIndicator(color: MrdTheme.secondary))
        : ListView.separated(
            padding: const EdgeInsets.all(12),
            itemCount: _items.length,
            separatorBuilder: (_, __) => const SizedBox(height: 8),
            itemBuilder: (_, i) {
              final inc = _items[i];
              return Card(
                child: ListTile(
                  leading: CircleAvatar(
                    backgroundColor: _prioColor(inc.prioridad).withOpacity(0.15),
                    child: Icon(Icons.warning_amber, color: _prioColor(inc.prioridad), size: 20),
                  ),
                  title: Text(inc.titulo, style: const TextStyle(fontWeight: FontWeight.w600)),
                  subtitle: Text('${inc.estado} · ${inc.herramientaNombre ?? "Sin herramienta"}',
                    style: const TextStyle(fontSize: 12)),
                  trailing: Chip(
                    label: Text(inc.prioridad, style: const TextStyle(fontSize: 11)),
                    backgroundColor: _prioColor(inc.prioridad).withOpacity(0.15),
                    side: BorderSide.none,
                    padding: EdgeInsets.zero,
                    labelPadding: const EdgeInsets.symmetric(horizontal: 8),
                  ),
                ),
              );
            },
          ),
      floatingActionButton: FloatingActionButton.extended(
        onPressed: () => Navigator.push(context,
          MaterialPageRoute(builder: (_) => const NuevaIncidenciaScreen())),
        backgroundColor: MrdTheme.secondary,
        icon: const Icon(Icons.add, color: Colors.white),
        label: const Text('Nueva', style: TextStyle(color: Colors.white)),
      ),
    );
  }
}

class NuevaIncidenciaScreen extends StatefulWidget {
  const NuevaIncidenciaScreen({super.key});
  @override
  State<NuevaIncidenciaScreen> createState() => _NuevaIncidenciaScreenState();
}

class _NuevaIncidenciaScreenState extends State<NuevaIncidenciaScreen> {
  final _formKey = GlobalKey<FormState>();
  final _tituloCtrl = TextEditingController();
  final _descCtrl = TextEditingController();
  String _prioridad = 'media';
  File? _foto;
  final _signCtrl = SignatureController(penStrokeWidth: 3, penColor: Colors.white, exportBackgroundColor: Colors.black);
  bool _showFirma = false;
  bool _saving = false;

  Future<void> _tomarFoto() async {
    final picker = ImagePicker();
    final img = await picker.pickImage(source: ImageSource.camera, imageQuality: 80);
    if (img != null) setState(() => _foto = File(img.path));
  }

  Future<void> _guardar() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _saving = true);
    final data = {
      'titulo': _tituloCtrl.text.trim(),
      'descripcion': _descCtrl.text.trim(),
      'prioridad': _prioridad,
    };
    final result = await ApiService.instance.safePost('/api/v1/incidencias', data);
    if (!mounted) return;
    setState(() => _saving = false);
    if (result['queued'] == true) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Guardado offline. Se sincronizará al conectarse.'),
          backgroundColor: MrdTheme.warning));
    } else {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Incidencia creada.'), backgroundColor: MrdTheme.success));
    }
    Navigator.pop(context);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Nueva Incidencia')),
      body: Form(
        key: _formKey,
        child: ListView(
          padding: const EdgeInsets.all(16),
          children: [
            TextFormField(
              controller: _tituloCtrl,
              decoration: const InputDecoration(labelText: 'Título *'),
              validator: (v) => (v?.isEmpty ?? true) ? 'Requerido' : null,
            ),
            const SizedBox(height: 12),
            TextFormField(
              controller: _descCtrl,
              decoration: const InputDecoration(labelText: 'Descripción'),
              maxLines: 3,
            ),
            const SizedBox(height: 12),
            DropdownButtonFormField<String>(
              value: _prioridad,
              decoration: const InputDecoration(labelText: 'Prioridad'),
              items: const [
                DropdownMenuItem(value: 'baja', child: Text('Baja')),
                DropdownMenuItem(value: 'media', child: Text('Media')),
                DropdownMenuItem(value: 'alta', child: Text('Alta')),
              ],
              onChanged: (v) => setState(() => _prioridad = v!),
            ),
            const SizedBox(height: 16),

            // Foto
            Text('Fotografía', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            if (_foto != null)
              ClipRRect(
                borderRadius: BorderRadius.circular(10),
                child: Image.file(_foto!, height: 180, fit: BoxFit.cover),
              ),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: _tomarFoto,
              icon: const Icon(Icons.camera_alt),
              label: Text(_foto == null ? 'Tomar foto' : 'Cambiar foto'),
            ),
            const SizedBox(height: 16),

            // Firma
            Text('Firma digital', style: Theme.of(context).textTheme.titleMedium),
            const SizedBox(height: 8),
            OutlinedButton.icon(
              onPressed: () => setState(() => _showFirma = !_showFirma),
              icon: const Icon(Icons.draw),
              label: Text(_showFirma ? 'Ocultar firma' : 'Añadir firma'),
            ),
            if (_showFirma) ...[
              const SizedBox(height: 8),
              Container(
                height: 150,
                decoration: BoxDecoration(
                  color: Colors.black,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: Colors.white24),
                ),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(10),
                  child: Signature(controller: _signCtrl, backgroundColor: Colors.black),
                ),
              ),
              TextButton(
                onPressed: () => _signCtrl.clear(),
                child: const Text('Borrar firma', style: TextStyle(color: MrdTheme.danger)),
              ),
            ],
            const SizedBox(height: 24),
            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: _saving ? null : _guardar,
                child: _saving
                  ? const CircularProgressIndicator(strokeWidth: 2, color: Colors.white)
                  : const Text('Crear incidencia'),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
