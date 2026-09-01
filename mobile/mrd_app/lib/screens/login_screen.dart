import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import '../services/auth_service.dart';
import '../config/theme.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});
  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final _formKey = GlobalKey<FormState>();
  final _userCtrl = TextEditingController();
  final _passCtrl = TextEditingController();
  bool _showPass = false;
  String? _error;
  bool _bioAvailable = false;

  @override
  void initState() {
    super.initState();
    _checkBiometric();
  }

  Future<void> _checkBiometric() async {
    final auth = context.read<AuthService>();
    final available = await auth.biometricAvailable();
    if (mounted) setState(() => _bioAvailable = available && auth.biometricEnabled);
    if (_bioAvailable) _loginBio();
  }

  Future<void> _loginBio() async {
    final auth = context.read<AuthService>();
    final ok = await auth.authenticateWithBiometrics();
    if (ok && mounted) Navigator.pushReplacementNamed(context, '/home');
  }

  Future<void> _loginPass() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() => _error = null);
    final auth = context.read<AuthService>();
    final result = await auth.login(_userCtrl.text.trim(), _passCtrl.text);
    if (!mounted) return;
    if (result['ok'] == true) {
      Navigator.pushReplacementNamed(context, '/home');
    } else {
      setState(() => _error = result['error'] as String?);
    }
  }

  @override
  Widget build(BuildContext context) {
    final auth = context.watch<AuthService>();
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(28),
            child: Form(
              key: _formKey,
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                children: [
                  // Logo
                  Container(
                    width: 84, height: 84,
                    decoration: BoxDecoration(
                      color: MrdTheme.primary,
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: const Icon(Icons.construction, color: MrdTheme.secondary, size: 48),
                  ),
                  const SizedBox(height: 20),
                  Text('MRD TOOL CONTROL',
                    style: Theme.of(context).textTheme.titleLarge?.copyWith(fontSize: 22)),
                  const SizedBox(height: 6),
                  Text('v2.1.0 — Aplicación Móvil',
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(fontSize: 12)),
                  const SizedBox(height: 36),

                  // Usuario
                  TextFormField(
                    controller: _userCtrl,
                    decoration: const InputDecoration(
                      labelText: 'Usuario',
                      prefixIcon: Icon(Icons.person_outline),
                    ),
                    validator: (v) => (v == null || v.isEmpty) ? 'Requerido' : null,
                    textInputAction: TextInputAction.next,
                    autocorrect: false,
                  ),
                  const SizedBox(height: 14),

                  // Contraseña
                  TextFormField(
                    controller: _passCtrl,
                    obscureText: !_showPass,
                    decoration: InputDecoration(
                      labelText: 'Contraseña',
                      prefixIcon: const Icon(Icons.lock_outline),
                      suffixIcon: IconButton(
                        icon: Icon(_showPass ? Icons.visibility_off : Icons.visibility),
                        onPressed: () => setState(() => _showPass = !_showPass),
                      ),
                    ),
                    validator: (v) => (v == null || v.isEmpty) ? 'Requerido' : null,
                    textInputAction: TextInputAction.done,
                    onFieldSubmitted: (_) => _loginPass(),
                  ),
                  const SizedBox(height: 8),

                  // Error
                  if (_error != null)
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(10),
                      margin: const EdgeInsets.only(bottom: 8),
                      decoration: BoxDecoration(
                        color: MrdTheme.danger.withOpacity(0.15),
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: MrdTheme.danger.withOpacity(0.4)),
                      ),
                      child: Text(_error!, style: const TextStyle(color: MrdTheme.danger, fontSize: 13)),
                    ),

                  const SizedBox(height: 16),

                  // Botón login
                  SizedBox(
                    width: double.infinity,
                    child: ElevatedButton(
                      onPressed: auth.loading ? null : _loginPass,
                      child: auth.loading
                        ? const SizedBox(width: 20, height: 20,
                            child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                        : const Text('Iniciar sesión'),
                    ),
                  ),

                  // Biométrico
                  if (_bioAvailable) ...[
                    const SizedBox(height: 16),
                    OutlinedButton.icon(
                      onPressed: _loginBio,
                      icon: const Icon(Icons.fingerprint, size: 22),
                      label: const Text('Usar huella / Face ID'),
                      style: OutlinedButton.styleFrom(
                        minimumSize: const Size(double.infinity, 48),
                        side: const BorderSide(color: MrdTheme.accent),
                        foregroundColor: MrdTheme.accent,
                      ),
                    ),
                  ],

                  const SizedBox(height: 32),
                  Text('© 2025 MRD Estructuras',
                    style: Theme.of(context).textTheme.bodyMedium?.copyWith(fontSize: 11)),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  @override
  void dispose() {
    _userCtrl.dispose();
    _passCtrl.dispose();
    super.dispose();
  }
}
