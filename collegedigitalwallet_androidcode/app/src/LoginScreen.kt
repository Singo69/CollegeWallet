package com.example.collegedigitalwallet

import android.widget.Toast
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.navigation.NavController
import com.example.collegedigitalwallet.api.RetrofitClient
import com.example.collegedigitalwallet.model.LoginRequest
import com.example.collegedigitalwallet.model.LoginResponse
import retrofit2.Call
import retrofit2.Callback
import retrofit2.Response
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Visibility
import androidx.compose.material.icons.filled.VisibilityOff
import androidx.compose.ui.text.input.VisualTransformation
import androidx.compose.material3.IconButton

@Composable
fun LoginScreen(navController: NavController) {
    // IMPORTANT: login is username + password
    var username by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var passwordVisible by remember { mutableStateOf(false) }
    var loading by remember { mutableStateOf(false) }

    val context = LocalContext.current

    val bg = Brush.verticalGradient(
        colors = listOf(
            Color(0xFF0B0F2B),
            Color(0xFF1A237E),
            Color(0xFF283593)
        )
    )

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(bg),
        contentAlignment = Alignment.Center
    ) {
        Card(
            modifier = Modifier
                .padding(horizontal = 26.dp)
                .fillMaxWidth(),
            shape = RoundedCornerShape(26.dp),
            colors = CardDefaults.cardColors(containerColor = Color(0xFFF2F2F2)),
            elevation = CardDefaults.cardElevation(10.dp)
        ) {
            Column(
                modifier = Modifier
                    .padding(horizontal = 26.dp, vertical = 22.dp),
                horizontalAlignment = Alignment.CenterHorizontally
            ) {
                // Logo
                Row(
                    modifier = Modifier.fillMaxWidth(),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalArrangement = Arrangement.Center
                ) {
                    Image(
                        painter = painterResource(id = R.drawable.ick_logo),
                        contentDescription = "Islington",
                        modifier = Modifier
                            .height(70.dp)
                            .padding(top = 4.dp)
                    )
                }

                Spacer(modifier = Modifier.height(18.dp))

                Text(
                    text = "Login",
                    style = MaterialTheme.typography.headlineMedium,
                    fontWeight = FontWeight.Bold,
                    color = Color.Black
                )

                Spacer(modifier = Modifier.height(22.dp))

                // Username field (still your same pill UI)
                OutlinedTextField(
                    value = username,
                    onValueChange = { username = it },
                    placeholder = { Text("Username") }, // was "Student ID" (but backend uses username)
                    singleLine = true,
                    enabled = !loading,
                    shape = RoundedCornerShape(14.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedContainerColor = Color(0xFFE1E1E1),
                        unfocusedContainerColor = Color(0xFFE1E1E1),
                        focusedBorderColor = Color.Transparent,
                        unfocusedBorderColor = Color.Transparent,
                        focusedTextColor = Color.Black,
                        unfocusedTextColor = Color.Black
                    ),
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(54.dp)
                )

                Spacer(modifier = Modifier.height(14.dp))

                // Password field
                OutlinedTextField(
                    value = password,
                    onValueChange = { password = it },
                    placeholder = { Text("Password") },
                    singleLine = true,
                    enabled = !loading,
                    visualTransformation = if (passwordVisible) VisualTransformation.None else PasswordVisualTransformation(),
                    trailingIcon = {
                        if (password.isNotEmpty()) {
                            IconButton(onClick = { passwordVisible = !passwordVisible }) {
                                Icon(
                                    imageVector = if (passwordVisible) Icons.Filled.VisibilityOff else Icons.Filled.Visibility,
                                    contentDescription = if (passwordVisible) "Hide password" else "Show password",
                                    tint = Color.DarkGray
                                )
                            }
                        }
                    },
                    shape = RoundedCornerShape(14.dp),
                    colors = OutlinedTextFieldDefaults.colors(
                        focusedContainerColor = Color(0xFFE1E1E1),
                        unfocusedContainerColor = Color(0xFFE1E1E1),
                        focusedBorderColor = Color.Transparent,
                        unfocusedBorderColor = Color.Transparent,
                        focusedTextColor = Color.Black,
                        unfocusedTextColor = Color.Black
                    ),
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(54.dp)
                )

                Spacer(modifier = Modifier.height(22.dp))

                Button(
                    enabled  = !loading,
                    onClick = {
                        val u = username.trim()
                        val p = password

                        if (u.isBlank() || p.isBlank()) {
                            Toast.makeText(context, "Enter username and password", Toast.LENGTH_SHORT).show()
                            return@Button
                        }

                        loading = true

                        val request = LoginRequest(u, p)
                        RetrofitClient.api.login(request).enqueue(object : Callback<LoginResponse> {
                            override fun onResponse(
                                call: Call<LoginResponse>,
                                response: Response<LoginResponse>
                            ) {
                                loading = false
                                val body = response.body()

                                if (response.isSuccessful && body?.status == "success") {
                                    // Save session (keep field names consistent with backend response)
                                    UserSession.username = body.username
                                    UserSession.studentId = body.studentId
                                    UserSession.program = body.program
                                    UserSession.balance = body.balance
                                    UserSession.fullName = body.full_name

                                    Toast.makeText(context, "Login successful ✅", Toast.LENGTH_SHORT).show()

                                    // Navigate cleanly (prevents weird back behavior)
                                    navController.navigate("wallet") {
                                        popUpTo("login") { inclusive = true }
                                    }
                                } else {
                                    Toast.makeText(
                                        context,
                                        body?.message ?: "Invalid username or password",
                                        Toast.LENGTH_SHORT
                                    ).show()
                                }
                            }

                            override fun onFailure(call: Call<LoginResponse>, t: Throwable) {
                                loading = false
                                val msg = t.message ?: t.javaClass.simpleName
                                Toast.makeText(context, "Login error: $msg", Toast.LENGTH_LONG).show()
                                android.util.Log.e("LOGIN_API", "Login failed", t)
                            }
                        })
                    },
                    shape = RoundedCornerShape(18.dp),
                    colors = ButtonDefaults.buttonColors(
                        containerColor = Color(0xFFDDDDDD),
                        contentColor = Color.Black
                    ),
                    modifier = Modifier
                        .width(150.dp)
                        .height(48.dp)
                ) {
                    Text(if (loading) "Loading..." else "Submit", fontWeight = FontWeight.SemiBold)
                }
            }
        }
    }
}